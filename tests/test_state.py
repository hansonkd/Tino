from tino import Tino, ConnState
from pydantic import BaseModel
import datetime
from typing import List, Dict, Optional
import pytest
from aioredis import ReplyError


def state_factory():
    return 0


api = Tino(state_factory=state_factory)


@api.command
async def increment(a: int, state: ConnState) -> None:
    state.value += a


@api.command
async def get(state: ConnState) -> int:
    return state.value


@pytest.mark.asyncio
async def test_api_success():
    async with api.test_server_with_client() as client:
        result = await client.get()
        assert result == 0
        await client.increment(1)
        result = await client.get()
        assert result == 1
