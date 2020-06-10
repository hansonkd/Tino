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
