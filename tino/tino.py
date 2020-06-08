import asyncio
import inspect
import msgpack
import json
from contextlib import asynccontextmanager

from pydantic import ValidationError
from pydantic.tools import parse_obj_as
from aioredis.parser import Reader
from aioredis.stream import StreamReader
from aioredis import create_redis_pool
from asyncio.streams import StreamReaderProtocol

MAX_CHUNK_SIZE = 65536
OK = b"+OK\r\n"
COMMAND_PING = b"PING"
PONG = b"+PONG\r\n"
COMMAND_QUIT = b"QUIT"
COMMAND_AUTH = b"AUTH"
BUILT_IN_COMMANDS = (COMMAND_PING, COMMAND_QUIT, COMMAND_AUTH)


from typing import List
import datetime
from decimal import Decimal
from enum import Enum
from ipaddress import (
    IPv4Address,
    IPv4Interface,
    IPv4Network,
    IPv6Address,
    IPv6Interface,
    IPv6Network,
)
from pathlib import Path
from types import GeneratorType
from typing import Any, Callable, Dict, Type, Union
from uuid import UUID
from pydantic import BaseModel


def isoformat(o):
    return o.isoformat()


ENCODERS_BY_TYPE: Dict[Type[Any], Callable[[Any], Any]] = {
    datetime.date: isoformat,
    datetime.datetime: isoformat,
    datetime.time: isoformat,
    datetime.timedelta: lambda td: td.total_seconds(),
    Decimal: float,
    Enum: lambda o: o.value,
    frozenset: list,
    GeneratorType: list,
    IPv4Address: str,
    IPv4Interface: str,
    IPv4Network: str,
    IPv6Address: str,
    IPv6Interface: str,
    IPv6Network: str,
    Path: str,
    set: list,
    UUID: str,
}


def default(obj):
    if isinstance(obj, BaseModel):
        return obj.dict()

    encoder = ENCODERS_BY_TYPE.get(type(obj))
    if encoder:
        return encoder(obj)
    return obj


def pack_msgpack(obj):
    return msgpack.packb(obj, default=default)


async def write_permission_denied(writer):
    writer.write(b"-PERMISSION_DENIED\r\n")
    await writer.drain()


class Command:
    def __init__(self, command, signature, return_type, handler):
        self.command = command
        self.signature = signature
        self.num_args = len([arg_name for arg_name, arg_type in self.signature if arg_type not in (Auth, AuthRequired, ConnState)])
        self.handler = handler
        self.return_type = return_type

    async def execute(self, redis_list, writer, state, auth):
        args = []
        if len(redis_list) != self.num_args:
            writer.write(b"-NUM_ARG_MISMATCH\r\n")
            await writer.drain()
            return True

        pos = 0
        for (arg_name, arg_type) in self.signature:
            if arg_type == Auth:
                args.append(auth)
                continue
            elif arg_type == AuthRequired:
                if not auth.value:
                    await write_permission_denied(writer)
                    return True
                args.append(AuthRequired(auth.value))
                continue
            elif arg_type == ConnState:
                args.append(state)
                continue

            redis_value = redis_list[pos]
            pos += 1

            try:
                raw_value = msgpack.unpackb(redis_value)
            except msgpack.UnpackException as e:
                loc = json.dumps(["command", arg_name])
                msg = json.dumps("invalid msgpack")
                writer.write(f"-INVALID_MSGPACK {loc} {msg}\r\n".encode("utf8"))
                await writer.drain()
                return True

            try:
                obj = parse_obj_as(arg_type, raw_value)
            except ValidationError as e:
                err = e.errors()[0]
                loc = json.dumps(("command", arg_name) + err["loc"][1:])
                msg = json.dumps(err["msg"])
                t = json.dumps(err["type"])
                writer.write(f"-VALIDATION_ERROR {loc} {msg} {t}\r\n".encode("utf8"))
                await writer.drain()
                return True
            args.append(obj)

        result = await self.handler(*args)
        to_send = pack_msgpack(result)
        writer.write(b"$%d\r\n%b\r\n" % (len(to_send), to_send))
        await writer.drain()
        return False


class Auth:
    def __init__(self, auth_state):
        self.value = auth_state

class AuthRequired:
    def __init__(self, auth_state):
        self.value = auth_state


class ConnState:
    def __init__(self, value):
        self.value = value


class Tino:
    def __init__(self, host="localhost", port=7777, auth_func=None, state_factory=None):
        self.host = host
        self.port = port
        self.commands = {}
        self.auth_func = auth_func
        self.state_factory = state_factory

    def command(self, f):
        name = f.__name__.upper().encode("utf8")
        if name in BUILT_IN_COMMANDS:
            raise Exception(f'Creating a command with name "{f.__name__}" is not allowed because it conflicts with a built in command.')
        sig = inspect.signature(f)
        ts_ = [(k, v.annotation) for k, v in sig.parameters.items()]
        self.commands[name] = Command(name, ts_, sig.return_annotation, f)
        return f

    async def handle_connection(self, reader, writer):
        if self.state_factory:
            state = ConnState(self.state_factory())
        else:
            state = ConnState(None)
        
        auth = Auth(None)

        try:
            while True:
                data = await reader.readobj()
                if not data:
                    break
                incoming_command = data[0]
                if incoming_command == COMMAND_QUIT:
                    break
                elif incoming_command == COMMAND_PING:
                    writer.write(PONG)
                    await writer.drain()
                    continue
                elif incoming_command == COMMAND_AUTH:
                    new_auth = await self.auth_func(*data[1:])
                    if new_auth:
                        auth.value = new_auth
                        writer.write(OK)
                        await writer.drain()
                        continue
                    else:
                        auth.value = None
                        await write_permission_denied(writer)
                        break

                try:
                    command = self.commands[incoming_command]
                except KeyError:
                    writer.write(b"-INVALID_COMMAND %b\r\n" % incoming_command)
                    await writer.drain()
                    break

                try:
                    should_break = await command.execute(data[1:], writer, state, auth)
                except Exception as e:
                    should_break = True
                    msg = json.dumps(str(e))
                    writer.write(f"-UNEXPECTED_ERROR {msg}\r\n".encode("utf8"))
                    await writer.drain()
                    raise e

                if should_break:
                    break
        finally:
            writer.close()
            await writer.wait_closed()

    async def create_server(self, loop=None, host=None, port=None, **kwargs):
        loop = loop or asyncio.get_event_loop()

        def factory():
            reader = StreamReader(limit=MAX_CHUNK_SIZE, loop=loop)
            reader.set_parser(Reader())
            return StreamReaderProtocol(reader, self.handle_connection, loop=loop)

        return await loop.create_server(
            factory, host or self.host, port or self.port, **kwargs
        )

    @asynccontextmanager
    async def test_server_with_client(self, host="localhost", port=1531, password=None):
        client_class = make_client_class(self)
        server = await self.create_server(host=host, port=port)
        client = client_class()
        try:
            await client.connect(f"redis://{host}:{port}", password=password)
            yield client
        finally:
            await client.close()
            server.close()
            await server.wait_closed()

    def run(self, **kwargs):
        loop = asyncio.get_event_loop()

        coro = self.create_server(loop=loop, **kwargs)
        server = loop.run_until_complete(coro)
        try:
            loop.run_forever()
        except KeyboardInterrupt:
            pass

        server.close()
        loop.run_until_complete(server.wait_closed())
        loop.close()


class Client:
    def __init__(self, redis=None):
        self.redis = redis

    async def connect(self, redis_url="redis://localhost:7777", *args, **kwargs):
        self.redis = await create_redis_pool(redis_url, *args, **kwargs)

    async def close(self):
        if self.redis:
            self.redis.close()
            await self.redis.wait_closed()


def make_client_class(api: Tino):
    methods = {}
    for name, command in api.commands.items():
        async def call(self, *args, command=command):
            packed = [pack_msgpack(arg) for arg in args]
            result = await self.redis.execute(command.command, *packed)
            r = msgpack.unpackb(result)
            if command.return_type != None:
                return parse_obj_as(command.return_type, r)
        methods[name.lower().decode("utf8")] = call
    return type("BoundClient", (Client,), methods)


def make_mock_client(api: Tino):
    methods = {}
    for name, command in api.commands.items():

        async def call(self, *args):
            command.handle(*args)

        methods[name.lower().decode("utf8")] = call
    return type("BoundClient", (Client,), methods)
