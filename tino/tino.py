import asyncio
import sys
import inspect
import msgpack
import json
import logging
from contextlib import asynccontextmanager

from pydantic import ValidationError
from pydantic.tools import parse_obj_as
from aioredis.parser import Reader
from aioredis.stream import StreamReader
from aioredis import create_redis_pool
from asyncio.streams import StreamReaderProtocol


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

import uvicorn
from uvicorn.supervisors.multiprocess import Multiprocess


logger = logging.getLogger("uvicorn.error")

MAX_CHUNK_SIZE = 65536
OK = b"+OK\r\n"
COMMAND_PING = b"PING"
PONG = b"+PONG\r\n"
COMMAND_QUIT = b"QUIT"
COMMAND_AUTH = b"AUTH"
BUILT_IN_COMMANDS = (COMMAND_PING, COMMAND_QUIT, COMMAND_AUTH)


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
    if hasattr(obj, "__dict__"):
        return dict(obj)

    encoder = ENCODERS_BY_TYPE.get(type(obj))
    if encoder:
        return encoder(obj)
    return obj


def pack_msgpack(packer, obj):
    return packer.pack(obj)


async def write_permission_denied(writer):
    writer.write(b"-PERMISSION_DENIED\r\n")
    await writer.drain()


class Command:
    def __init__(self, command, signature, return_type, handler):
        self.command = command
        self.signature = signature
        self.num_args = len(
            [
                arg_name
                for arg_name, arg_type in self.signature
                if arg_type not in (Auth, AuthRequired, ConnState)
            ]
        )
        self.handler = handler
        self.return_type = return_type


    async def execute(self, redis_list, writer, state, auth, packer):
        try:
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
            to_send = pack_msgpack(packer, result)
            writer.write(b"$%d\r\n%b\r\n" % (len(to_send), to_send))
            await writer.drain()
            return False
        except Exception as e:
            msg = json.dumps(str(e))
            writer.write(f"-UNEXPECTED_ERROR {msg}\r\n".encode("utf8"))
            await writer.drain()
            
            raise e


class Auth:
    def __init__(self, auth_state):
        self.value = auth_state


class AuthRequired:
    def __init__(self, auth_state):
        self.value = auth_state


class ConnState:
    def __init__(self, value):
        self.value = value

class MyRunner:
    def __init__(self, app, server):
        self.app = app
        self.server = server
        self.packer = msgpack.Packer(default=default)

    async def handle_connection(self, reader, writer):
        if self.app.state_factory:
            state = ConnState(self.app.state_factory())
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
                    writer.write(OK)
                    await writer.drain()
                    break
                elif incoming_command == COMMAND_PING:
                    writer.write(PONG)
                    await writer.drain()
                    continue
                elif incoming_command == COMMAND_AUTH:
                    new_auth = await self.app.auth_func(*data[1:])
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
                    command = self.app.commands[incoming_command]
                except KeyError:
                    writer.write(b"-INVALID_COMMAND %b\r\n" % incoming_command)
                    await writer.drain()
                    break

                should_break = await command.execute(data[1:], writer, state, auth, self.packer)
                if should_break:
                    break
        finally:
            writer.close()
            await writer.wait_closed()

class Server(uvicorn.Server):

    def protocol_factory(self, loop=None):
        reader = StreamReader(limit=MAX_CHUNK_SIZE, loop=loop)
        reader.set_parser(Reader())
        runner = MyRunner(self.config.loaded_app, self)
        return StreamReaderProtocol(reader, runner.handle_connection, loop=loop)

    async def startup(self, sockets=None):
        await self.lifespan.startup()
        if self.lifespan.should_exit:
            self.should_exit = True
            return

        config = self.config

        loop = asyncio.get_event_loop()

        if sockets is not None:
            # Explicitly passed a list of open sockets.
            # We use this when the server is run from a Gunicorn worker.
            self.servers = []
            for sock in sockets:
                server = await loop.create_server(
                    self.protocol_factory, sock=sock, ssl=config.ssl, backlog=config.backlog
                )
                self.servers.append(server)

        else:
            # Standard case. Create a socket from a host/port pair.
            try:
                server = await loop.create_server(
                    self.protocol_factory,
                    host=config.host,
                    port=config.port,
                    ssl=config.ssl,
                )
            except OSError as exc:
                logger.error(exc)
                await self.lifespan.shutdown()
                sys.exit(1)
            port = config.port
            if port == 0:
                port = server.sockets[0].getsockname()[1]
            message = "Tino running on redis://%s:%d (Press CTRL+C to quit)"
            logger.info(
                message,
                config.host,
                port,
            )
            self.servers = [server]

        self.started = True

        for f in self.config.loaded_app.startup_funcs:
            await f()


    async def shutdown(self, sockets=None):
        await super().shutdown(sockets=sockets)
        for f in self.config.loaded_app.shutdown_funcs:
            await f()


    async def start_serving_tests(self):
        sockets = None
        config = self.config
        if not config.loaded:
            config.load()

class Tino:
    def __init__(self, auth_func=None, state_factory=None, loop=None):
        self.commands = {}
        self.auth_func = auth_func
        self.state_factory = state_factory
        self.startup_funcs = []
        self.shutdown_funcs = []

    def command(self, f):
        name = f.__name__.upper().encode("utf8")
        if name in BUILT_IN_COMMANDS:
            raise Exception(
                f'Creating a command with name "{f.__name__}" is not allowed because it conflicts with a built in command.'
            )
        sig = inspect.signature(f)
        ts_ = [(k, v.annotation) for k, v in sig.parameters.items()]
        self.commands[name] = Command(name, ts_, sig.return_annotation, f)
        return f

    def on_startup(self, f):
        self.startup_funcs.append(f)
        return f

    def on_shutdown(self, f):
        self.shutdown_funcs.append(f)
        return f

    def run(self, **kwargs):
        config = uvicorn.Config(self, **kwargs)
        server = Server(config=config)
        server.run()

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
    async def test_server_with_client(self, password=None, **kwargs):
        kwargs.setdefault("host", "localhost")
        kwargs.setdefault("port", 7534)

        config = uvicorn.Config(self,  proxy_headers=False, interface="tino", log_level="warning", **kwargs)
        server = Server(config=config)

        if not config.loaded:
            config.load()

        server.lifespan = config.lifespan_class(config)


        await server.startup(sockets=None)

        client_class = make_client_class(self)
        client = client_class()

        try:
            await client.connect(f"redis://{config.host}:{config.port}", password=password)
            yield client
        finally:
            await server.shutdown(sockets=None)
            client.close()
            await client.wait_closed()
            

    # async def start_server(self, loop=None, **kwargs):
    #     server = await self.create_server(loop=loop, **kwargs)
    #     for f in self.startup_funcs:
    #         await f()
    #     return server

    # async def stop_server(self, server):
    #     server.close()
    #     await server.wait_closed()
    #     for f in self.shutdown_funcs:
    #         await f()

    # def run(self, **kwargs):
    #     loop = asyncio.get_event_loop()

    #     server = loop.run_until_complete(self.start_server(loop=loop, **kwargs))
    #     try:
    #         loop.run_forever()
    #     except KeyboardInterrupt:
    #         pass

    #     loop.run_until_complete(self.stop_server(server))
    #     loop.close()



    def client(self):
        klass = make_client_class(self)
        return klass()


class Client:
    def __init__(self, redis=None):
        self.redis = redis

    async def connect(self, redis_url="redis://localhost:7777", *args, **kwargs):
        self.redis = await create_redis_pool(redis_url, *args, **kwargs)

    def close(self):
        if self.redis:
            self.redis.close()

    async def wait_closed(self):
        if self.redis:
            await self.redis.wait_closed()


def make_client_class(api: Tino):
    methods = {}
    for name, command in api.commands.items():
        async def call(self, *args, command=command):
            packer = msgpack.Packer(default=default)
            packed = [pack_msgpack(packer, arg) for arg in args]
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


def run(app: str, **kwargs):
    config = uvicorn.Config(app, proxy_headers=False, interface="tino", **kwargs)
    server = Server(config=config)

    if config.workers > 1:
        sock = config.bind_socket()
        supervisor = Multiprocess(config, target=server.run, sockets=[sock])
        supervisor.run()
    else:
        server.run()

