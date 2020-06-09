from tino import Tino, Auth, AuthRequired
from pydantic import BaseModel
import datetime
from typing import List, Dict, Optional
import pytest
from aioredis import ReplyError


async def authorize(password):
    if password == b"test123":
        return password


api = Tino(auth_func=authorize)


@api.command
async def echo(a: int, auth: AuthRequired) -> int:
    return a


@api.command
async def echo_auth(auth: Auth) -> Optional[bytes]:
    return auth.value


@pytest.mark.asyncio
async def test_api_success():
    async with api.test_server_with_client(password="test123") as client:
        result = await client.echo(1)
        assert result == 1


@pytest.mark.asyncio
async def test_api_permission_denied():
    async with api.test_server_with_client() as client:
        with pytest.raises(ReplyError) as e:
            await client.echo(1)
        assert str(e.value) == "PERMISSION_DENIED"


@pytest.mark.asyncio
async def test_api_wrong_password():
    with pytest.raises(ReplyError) as e:
        async with api.test_server_with_client(password="notthepassword"):
            pass
    assert str(e.value) == "PERMISSION_DENIED"


@pytest.mark.asyncio
async def test_api_echo_auth():
    async with api.test_server_with_client(password="test123") as client:
        auth_key = await client.echo_auth()
        assert auth_key == b"test123"


@pytest.mark.asyncio
async def test_api_echo_auth_none():
    async with api.test_server_with_client() as client:
        auth_key = await client.echo_auth()
        assert auth_key == None
