import uvicorn

from .protocol import protocol_factory


class Config(uvicorn.Config):
    def __init__(self, *args, **kwargs):
        kwargs.setdefault("lifespan", "off")
        kwargs.setdefault("proxy_headers", False)
        kwargs.setdefault("interface", "tino")
        kwargs.setdefault("server_name", "Tino")
        kwargs.setdefault("protocol_name", "redis")
        kwargs.setdefault("http", protocol_factory)
        super().__init__(*args, **kwargs)
