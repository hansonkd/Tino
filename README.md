# Tino
The fastest, cutest, little API you ever did see

### What is Tino?

Tino is a framework to remotely call functions. It builds both clients and servers. 

Tradidtional APIs are JSON over HTTP. Tino is Msgpack over the Redis Serialization Protocol. This makes it go faster, use less bandwidth, and its binary format easier to understand.

### Highlights

* Redis Protocol
* MessagePack Serialization
* Pydantic for automatically parsing rich datastructures
* Fast. Up to 20x faster than the fastest HTTP Python framework.
* Small. Under 500 lines of code.

### Does Tino use Redis?

No. Tino uses RESP, the Redis Serialization Protocol, to encode messages over TCP. Tino only needs Redis if the service you build adds it.


### Generalizing the Redis Protocol

Tino was born after a long search to find an alternative to HTTP. The protocol is great for the web, but for backend server-to-server services, it is a bit overkill. HTTP2 tried to fix some of the problems, but ended up as is a mess of statemachines, multiplexing, and header compression algorithms that proper clients took years to come out and some languages still haven't implemented it fully.


[RESP](https://redis.io/topics/protocol), the Redis Serialization Protocol, is a Request-Response model with a very simple human readable syntax. It is also very fast to parse which makes it a great candidate for use in an API. After a [weekend of hacking](https://medium.com/swlh/hacking-the-redis-protocol-as-an-http-api-alternative-using-asyncio-in-python-7e57ba65dce3?source=friends_link&sk=029399a8cd40d6ef63895fd777459cad), a proof of concept was born and Tino quickly followed.


### MessagePack for Serialization

It is fast, can enable zero-copy string and bytes decoding, and the most important, it is [only an afternoon of hacking](https://medium.com/@hansonkd/building-beautiful-binary-parsers-in-elixir-1bd7f865bf17?source=friends_link&sk=6f7b440eb04ee81679c3ddfede9bab07) to get a serializer and parser going.

MessagePack paired with RESP means that you can implement the entire stack, protocol and serialization, by yourself from scratch if you needed to without too much trouble. And it will be fast.

### The Basics

Tino follows closely the design of [FastAPI](https://fastapi.tiangolo.com/). Type annotations are required for both arguments and return values so that values can automatically be parsed and serialized. In Redis all commands are arrays. The position of your argument in the signature of the function matches the position of the string array of the redis command. Tino commands can not contain keyword arguments. Tino will automatically fill in and parse Pydantic models.

```python
# server.py
from tino import Tino
from pydantic import BaseModel

app = Tino()

class NumberInput(BaseModel):
    value: int

@app.command
def add(a: int, b: NumberInput) -> int:
    return a + b.value

if __name__ == "__main__":
    app.run()
```

Now you can run commands against the server using any Redis api in any language as long as the client supports custom Redis commands (most do).

Or you can use Tino's builtin high-performance client:

```python
# client.py
import asyncio
from server import app, NumberInput # import the app from above

async def go():
    client = app.client()
    await client.connect()

    three = await client.add(1, NumberInput(value=2))

    client.close()
    await client.wait_closed()

if __name__ == "__main__":
    asyncio.run(go())
```


### Authorization

Tino has authorization by adding `AuthRequired` to the type signature of the methods you want to protect and supplying the `Tino` object with an `auth_func`. The `auth_func` takes a `bytes` object and returns `None` if the connection failed authorization or any other value symbolizing the authorization state if they succeeded.

```python
from tino import Tino

KEYS = {
    b'tinaspassword': 'tina'
}
def auth_func(password: bytes):
    return KEYS.get(password, None)

app = Tino(auth_func=auth_func)

@app.command
def add(a: int, b: int, auth: AuthRequired) -> int:
    print(auth.value)
    return a + b
```

And pass the password to the `client.connect`.

```python
async def do():
    client = app.client()
    await client.connect(password="tinaspassword")
```

### Other Magic Arguments

Besides `AuthRequired` you can also add `Auth` (where `auth.value` can be None) and `ConnState` to get the state if you also supply a `state_factory`. This state is mutatable and is private to the connection.

```python
from tino import Tino

async def state_factory():
    return 0

app = Tino(state_factory=state_factory)

@app.command
def add(a: int, b: int, auth: Auth, conn: ConnState) -> int:
    # Count the number of unauthorized calls on this connection.
    if auth.value is None:
        conn.value += 1
    return a + b

```


### Is Tino Secure?
Probably the biggest vulnerability is a DDOS attack. More testing needs to be done to see how Tino behaves under large message sizes. Currently placing views behind `AuthRequired` does not protect against this because the entire message is parsed. So for the time being, Tino should only be considered for private connections. This can be improved however, by parsing the command first, doing the permission check then reading and parsing the body.

### What about Databases?
For SQL I recommend using the [databases](https://pypi.org/project/databases/) project with SQLAlchemy to get true asyncio support. This example is borrowed from [fastapi](https://fastapi.tiangolo.com/advanced/async-sql-databases/)

```python
from tino import Tino
import databases
import sqlalchemy
from typing import List

# SQLAlchemy specific code, as with any other app
DATABASE_URL = "sqlite:///./test.db"
# DATABASE_URL = "postgresql://user:password@postgresserver/db"

database = databases.Database(DATABASE_URL)

metadata = sqlalchemy.MetaData()

notes = sqlalchemy.Table(
    "notes",
    metadata,
    sqlalchemy.Column("id", sqlalchemy.Integer, primary_key=True),
    sqlalchemy.Column("text", sqlalchemy.String),
    sqlalchemy.Column("completed", sqlalchemy.Boolean),
)


engine = sqlalchemy.create_engine(
    DATABASE_URL, connect_args={"check_same_thread": False}
)
metadata.create_all(engine)


class NoteIn(BaseModel):
    text: str
    completed: bool


class Note(BaseModel):
    id: int
    text: str
    completed: bool


app = Tino()

@app.on_startup
async def startup():
    await database.connect()


@app.on_shutdown
async def shutdown():
    await database.disconnect()

@app.command
async def read_notes() -> List[Note]:
    query = notes.select()
    rows = await database.fetch_all(query)
    return [Note(**n) for n in rows]


@app.command
async def create_note(note: NoteIn) -> Note:
    query = notes.insert().values(text=note.text, completed=note.completed)
    last_record_id = await database.execute(query)
    return Note(id=last_record_id, **note.dict())



if __name__ == "__main__":
    app.run()
```


### Should I use Tino in Production?

Its not ready for public consumption at the moment, but if you want my help to run it, just drop me a line.



### TLS Support

Its probably easiest to deploy Tino behind a TCP loadbalancer that already supports TLS. You can pass in the `SSLContext` to the `client.connect` function as kwargs to the Redis connection pool.

### Benchmarks

This is run with uvicorn as a single worker. `httpx` seemed to be a major point of performance problems so I also benchmarked against `ab` (apache benchmark). However, `httpx` results are typical of what you would see if you were using python-to-python communication.

<img width="934" alt="Screen Shot 2020-06-09 at 10 38 45 PM" src="https://user-images.githubusercontent.com/496914/84231198-72764980-aaa2-11ea-971d-fc4146a0dffc.png">


### Coming Soon

* Iterators
