import uvicorn


class Server(uvicorn.Server):
    async def startup(self, sockets=None):
        await super().startup(sockets=sockets)
        for f in self.config.loaded_app.startup_funcs:
            await f()

    async def shutdown(self, sockets=None):
        await super().shutdown(sockets=sockets)
        for f in self.config.loaded_app.shutdown_funcs:
            await f()
