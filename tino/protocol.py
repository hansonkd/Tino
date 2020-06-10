from aioredis.parser import Reader
from aioredis.stream import StreamReader
from asyncio.streams import StreamReaderProtocol
import msgpack
from .serializer import default


from .special_args import Auth, AuthRequired, ConnState

MAX_CHUNK_SIZE = 65536
OK = b"+OK\r\n"
COMMAND_PING = b"PING"
PONG = b"+PONG\r\n"
COMMAND_QUIT = b"QUIT"
COMMAND_AUTH = b"AUTH"
BUILT_IN_COMMANDS = (COMMAND_PING, COMMAND_QUIT, COMMAND_AUTH)


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

                try:
                    command = self.config.loaded_app.commands[incoming_command]
                except KeyError:
                    writer.write(b"-INVALID_COMMAND %b\r\n" % incoming_command)
                    await writer.drain()
                    break

                should_break = await command.execute(
                    data[1:], writer, state, auth, self.packer
                )
                if should_break:
                    break
        finally:
            writer.close()
            await writer.wait_closed()


def protocol_factory(config, server_state, loop=None):
    reader = StreamReader(limit=MAX_CHUNK_SIZE, loop=loop)
    reader.set_parser(Reader())
    runner = TinoHandler(config, server_state)
    return StreamReaderProtocol(reader, runner.handle_connection, loop=loop)
