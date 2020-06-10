from tino import Tino, make_client_class
from fastapi import FastAPI, Body
from pydantic import BaseModel
from typing import Dict, List
import time
import sys
import asyncio
import httpx
import multiprocessing


class ComplexModel(BaseModel):
    a: int
    b: bool
    c: List["ComplexModel"]
    d: Dict[str, "ComplexModel"]
    e: str
    f: str
    g: str
    h: str
    i: str


ComplexModel.update_forward_refs()


complex_obj = ComplexModel(
    a=1,
    b=True,
    c=[
        ComplexModel(
            a=1,
            b=True,
            c=[
                ComplexModel(
                    a=1,
                    b=True,
                    c=[],
                    d={},
                    e="some 😊 😊 string",
                    f="some 😊 😊 string",
                    g="some 😊 😊 string",
                    h="some 😊 😊 string",
                    i="some 😊 😊 string",
                ),
                ComplexModel(
                    a=1,
                    b=True,
                    c=[],
                    d={},
                    e="some 😊 😊 string",
                    f="some 😊 😊 string",
                    g="some 😊 😊 string",
                    h="some 😊 😊 string",
                    i="some 😊 😊 string",
                ),
            ],
            d={
                "f": ComplexModel(
                    a=1,
                    b=True,
                    c=[
                        ComplexModel(
                            a=1,
                            b=True,
                            c=[],
                            d={},
                            e="some 😊 😊 string",
                            f="some 😊 😊 string",
                            g="some 😊 😊 string",
                            h="some 😊 😊 string",
                            i="some 😊 😊 string",
                        )
                    ],
                    d={},
                    e="some 😊 😊 string",
                    f="some 😊 😊 string",
                    g="some 😊 😊 string",
                    h="some 😊 😊 string",
                    i="some 😊 😊 string",
                )
            },
            e="some 😊 😊 string",
            f="some 😊 😊 string",
            g="some 😊 😊 string",
            h="some 😊 😊 string",
            i="some 😊 😊 string",
        )
    ],
    d={
        "g": ComplexModel(
            a=1,
            b=True,
            c=[],
            d={},
            e="some 😊 😊 string",
            f="some 😊 😊 string",
            g="some 😊 😊 string",
            h="some 😊 😊 string",
            i="some 😊 😊 string",
        )
    },
    e="some 😊 😊 string",
    f="some 😊 😊 string",
    g="some 😊 😊 string",
    h="some 😊 😊 string",
    i="some 😊 😊 string",
)

simple_string = "😊 😊 😊" * 100

api = Tino()


@api.command
async def tino_echo_complex(a: ComplexModel) -> ComplexModel:
    return a


@api.command
async def tino_echo_simple(a: str) -> str:
    return a


client_class = make_client_class(api)

fapi = FastAPI()


@fapi.post("/fapi/echo/complex")
async def fapi_echo_complex(a: ComplexModel) -> ComplexModel:
    return a


class Echo(BaseModel):
    a: str


@fapi.post("/fapi/echo/simple")
async def fapi_echo_simple(a: str = Body(...)) -> str:
    return a


async def simple_echo_client_tino_simple(ntimes):
    client = client_class()
    await client.connect(minsize=1, maxsize=1)
    t1 = time.time()
    for _ in range(ntimes):
        await client.tino_echo_simple(simple_string)
    return time.time() - t1
    client.close()
    await client.wait_closed()


async def simple_echo_client_tino_simple_concurrent(ntimes):
    client = client_class()
    await client.connect(minsize=100, maxsize=100)
    t1 = time.time()

    futures = []
    for _ in range(ntimes):
        futures.append(client.tino_echo_simple(simple_string))

    await asyncio.gather(*futures)
    return time.time() - t1
    client.close()
    await client.wait_closed()


async def simple_echo_client_tino_complex_concurrent(ntimes):
    client = client_class()
    await client.connect(minsize=10, maxsize=10)
    t1 = time.time()

    futures = []
    for _ in range(ntimes):
        futures.append(client.tino_echo_complex(complex_obj))

    await asyncio.gather(*futures)
    return time.time() - t1
    client.close()
    await client.wait_closed()


async def simple_echo_client_tino_complex(ntimes):
    client = client_class()
    await client.connect()
    t1 = time.time()
    for _ in range(ntimes):
        await client.tino_echo_complex(complex_obj)
    return time.time() - t1
    client.close()
    await client.wait_closed()


async def simple_echo_client_fapi_simple(ntimes):
    async with httpx.AsyncClient() as client:
        t1 = time.time()
        for _ in range(ntimes):
            res = await client.post(
                "http://localhost:9999/fapi/echo/simple", json=simple_string
            )
            res.json()
        return time.time() - t1


async def simple_echo_client_fapi_simple_concurrent(ntimes):
    max_conns = 100
    limits = httpx.PoolLimits(hard_limit=max_conns)
    async with httpx.AsyncClient(timeout=600, pool_limits=limits) as client:

        futures = []
        for _ in range(max_conns):
            futures.append(
                client.post(
                    "http://localhost:9999/fapi/echo/simple", json=simple_string
                )
            )

        await asyncio.gather(*futures)
        print("warmed up")

        t1 = time.time()
        futures = []
        for _ in range(ntimes):
            futures.append(
                client.post(
                    "http://localhost:9999/fapi/echo/simple", json=simple_string
                )
            )

        await asyncio.gather(*futures)

        return time.time() - t1


async def simple_echo_client_fapi_concurrent_concurrent(ntimes):
    max_conns = 100
    limits = httpx.PoolLimits(hard_limit=max_conns)
    async with httpx.AsyncClient(timeout=600, pool_limits=limits) as client:

        futures = []
        for _ in range(max_conns):
            futures.append(
                client.post(
                    "http://localhost:9999/fapi/echo/simple", json=simple_string
                )
            )

        await asyncio.gather(*futures)
        print("warmed up")

        t1 = time.time()
        futures = []
        for _ in range(ntimes):
            futures.append(
                client.post(
                    "http://localhost:9999/fapi/echo/complex", json=complex_obj.dict()
                )
            )

        await asyncio.gather(*futures)

        return time.time() - t1


async def simple_echo_client_fapi_complex(ntimes):
    async with httpx.AsyncClient() as client:
        t1 = time.time()
        for _ in range(ntimes):
            res = await client.post(
                "http://localhost:9999/fapi/echo/complex", json=complex_obj.dict()
            )
            ComplexModel(**res.json())
        return time.time() - t1


NUM_TIMES = 100 * 1000
NUM_CONCURRENT = multiprocessing.cpu_count()
if __name__ == "__main__":
    # import uvloop
    # uvloop.install()
    if sys.argv[1] == "tino_client_simple":
        print(asyncio.run(simple_echo_client_tino_simple(NUM_TIMES)))
    elif sys.argv[1] == "tino_client_simple_concurrent":
        print(asyncio.run(simple_echo_client_tino_simple_concurrent(NUM_TIMES)))
    elif sys.argv[1] == "tino_client_complex_concurrent":
        print(asyncio.run(simple_echo_client_tino_complex_concurrent(NUM_TIMES)))
    elif sys.argv[1] == "tino_client_complex":
        print(asyncio.run(simple_echo_client_tino_complex(NUM_TIMES)))
    elif sys.argv[1] == "tino_server":
        api.run(workers=2, host="localhost", port=7777)
    elif sys.argv[1] == "tino_server_uvloop":
        import uvloop

        uvloop.install()
        api.run(workers=2, host="localhost", port=7777)
    elif sys.argv[1] == "fapi_client_simple":
        print(asyncio.run(simple_echo_client_fapi_simple(NUM_TIMES)))
    elif sys.argv[1] == "fapi_client_simple_concurrent":
        print(asyncio.run(simple_echo_client_fapi_simple_concurrent(NUM_TIMES)))
    elif sys.argv[1] == "fapi_client_complex_concurrent":
        print(asyncio.run(simple_echo_client_fapi_concurrent_concurrent(NUM_TIMES)))
    elif sys.argv[1] == "fapi_client_complex":
        print(asyncio.run(simple_echo_client_fapi_complex(NUM_TIMES)))
    elif sys.argv[1] == "fapi_server":
        import uvicorn

        uvicorn.run(fapi, host="0.0.0.0", port=9999, loop="asyncio", log_level="error")
    elif sys.argv[1] == "fapi_server_uvloop":
        import uvicorn

        uvicorn.run(fapi, host="0.0.0.0", port=9999, loop="uvloop", log_level="error")
