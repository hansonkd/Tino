import asyncio
import sys
import inspect
import msgpack
import json
import logging
from contextlib import asynccontextmanager

from pydantic.tools import parse_obj_as

from aioredis import create_redis_pool

from uvicorn.supervisors.multiprocess import Multiprocess

from .special_args import Auth, AuthRequired, ConnState
from .server import Server
from .config import Config
from .serializer import pack_msgpack, default
from .protocol import BUILT_IN_COMMANDS, COMMAND_SUBSCRIBE, write_permission_denied


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
        config = Config(self, **kwargs)
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

        config = Config(self, log_level="warning", **kwargs)
        server = Server(config=config)

        if not config.loaded:
            config.load()

        server.lifespan = config.lifespan_class(config)

        await server.startup(sockets=None)

        client_class = make_client_class(self)
        client = client_class()

        try:
            await client.connect(
                f"redis://{config.host}:{config.port}", password=password
            )
            yield client
        finally:
            await server.shutdown(sockets=None)
            client.close()
            await client.wait_closed()

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
    config = Config(app, proxy_headers=False, interface="tino", **kwargs)
    server = Server(config=config)

    if config.workers > 1:
        sock = config.bind_socket()
        supervisor = Multiprocess(config, target=server.run, sockets=[sock])
        supervisor.run()
    else:
        server.run()
