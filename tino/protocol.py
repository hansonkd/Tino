from aioredis.parser import Reader
from aioredis.stream import StreamReader
from asyncio.streams import StreamReaderProtocol
import msgpack
import json
from pydantic import ValidationError
from pydantic.tools import parse_obj_as


from .serializer import default, pack_msgpack


from .special_args import Auth, AuthRequired, ConnState

MAX_CHUNK_SIZE = 65536
OK = b"+OK\r\n"
COMMAND_PING = b"PING"
PONG = b"+PONG\r\n"
COMMAND_QUIT = b"QUIT"
COMMAND_AUTH = b"AUTH"
COMMAND_SUBSCRIBE = b"SUBSCRIBE"
COMMAND_ITER = b"ITER"
COMMAND_NEXT = b"NEXT"
COMMAND_SEND = b"SEND"
BUILT_IN_COMMANDS = (COMMAND_PING, COMMAND_QUIT, COMMAND_AUTH, COMMAND_SUBSCRIBE)


async def write_permission_denied(writer):
    writer.write(b"-PERMISSION_DENIED\r\n")
    await writer.drain()


class TinoHandler:
    def __init__(self, config, server_state):
        self.config = config
        self.server_state = server_state
        self.packer = msgpack.Packer(default=default)

    async def handle_connection(self, reader, writer):
        if self.config.loaded_app.state_factory:
            state = ConnState(self.config.loaded_app.state_factory())
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
                    new_auth = await self.config.loaded_app.auth_func(*data[1:])
                    if new_auth:
                        auth.value = new_auth
                        writer.write(OK)
                        await writer.drain()
                        continue
                    else:
                        auth.value = None
                        await write_permission_denied(writer)
                        break
                else:
                    try:
                        command = self.config.loaded_app.commands[incoming_command]
                    except KeyError:
                        writer.write(b"-INVALID_COMMAND %b\r\n" % incoming_command)
                        await writer.drain()
                        break

                    should_break = await self.execute(
                        command, data[1:], writer, state, auth, self.packer
                    )
                    if should_break:
                        break
        finally:
            writer.close()
            await writer.wait_closed()

    async def build_args(self, command, redis_list, writer, state, auth):
        args = []
        if len(redis_list) != command.num_args:
            writer.write(b"-NUM_ARG_MISMATCH\r\n")
            await writer.drain()
            return None

        pos = 0
        for (arg_name, arg_type) in command.signature:
            if arg_type == Auth:
                args.append(auth)
                continue
            elif arg_type == AuthRequired:
                if not auth.value:
                    await write_permission_denied(writer)
                    return None
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
                return None

            try:
                obj = parse_obj_as(arg_type, raw_value)
            except ValidationError as e:
                err = e.errors()[0]
                loc = json.dumps(("command", arg_name) + err["loc"][1:])
                msg = json.dumps(err["msg"])
                t = json.dumps(err["type"])
                writer.write(f"-VALIDATION_ERROR {loc} {msg} {t}\r\n".encode("utf8"))
                await writer.drain()
                return None
            args.append(obj)
        return args

    async def execute(self, command, redis_list, writer, state, auth, packer):
        try:
            args = await self.build_args(command, redis_list, writer, state, auth)
            if not args:
                return True
            result = await command.handler(*args)

            to_send = pack_msgpack(packer, result)
            writer.write(b"$%d\r\n%b\r\n" % (len(to_send), to_send))
            await writer.drain()
            return False
        except Exception as e:
            msg = json.dumps(str(e))
            writer.write(f"-UNEXPECTED_ERROR {msg}\r\n".encode("utf8"))
            await writer.drain()
            raise e


def protocol_factory(config, server_state, loop=None):
    reader = StreamReader(limit=MAX_CHUNK_SIZE, loop=loop)
    reader.set_parser(Reader())
    runner = TinoHandler(config, server_state)
    return StreamReaderProtocol(reader, runner.handle_connection, loop=loop)
