from tino import Tino
from pydantic import BaseModel
import datetime
from typing import List, Dict, Optional
import pytest
from aioredis import ReplyError


api = Tino()


class MyModel(BaseModel):
    dt = datetime.datetime


@api.command
async def awesome(a: int, b: bool, c: List[str], d: Optional[MyModel]) -> Dict:
    return {"a": a, "b": b, "c": c, "d": d}


@pytest.mark.asyncio
async def test_api_success():
    async with api.test_server_with_client() as client:
        result = await client.awesome(1, True, [], MyModel(dt=datetime.datetime.now()))
        assert result == {
            "a": 1,
            "b": True,
            "c": [],
            "d": MyModel(dt=datetime.datetime.now()),
        }


@pytest.mark.asyncio
async def test_api_one_list():
    async with api.test_server_with_client() as client:
        result = await client.awesome(
            1, True, ["boom"], MyModel(dt=datetime.datetime.now())
        )
        assert result == {
            "a": 1,
            "b": True,
            "c": ["boom"],
            "d": MyModel(dt=datetime.datetime.now()),
        }


@pytest.mark.asyncio
async def test_api_two_list():
    async with api.test_server_with_client() as client:
        result = await client.awesome(
            pow(2, 31), False, ["boom", "boom2"], MyModel(dt=datetime.datetime.now())
        )
        assert result == {
            "a": pow(2, 31),
            "b": False,
            "c": ["boom", "boom2"],
            "d": MyModel(dt=datetime.datetime.now()),
        }


@pytest.mark.asyncio
async def test_api_wrong_type():
    async with api.test_server_with_client() as client:
        with pytest.raises(ReplyError) as e:
            await client.awesome("abc", True, [], None)
        assert (
            str(e.value)
            == 'VALIDATION_ERROR ["command", "a"] "value is not a valid integer" "type_error.integer"'
        )


@pytest.mark.asyncio
async def test_api_wrong_command():
    async with api.test_server_with_client() as client:
        with pytest.raises(ReplyError) as e:
            await client.redis.execute("ABC")
        assert str(e.value) == "INVALID_COMMAND ABC"
