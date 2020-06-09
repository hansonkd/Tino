from tino import Tino
import databases
import sqlalchemy
from typing import List
from pydantic import BaseModel

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
