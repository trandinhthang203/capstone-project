# checkpointer.py
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver  
from psycopg_pool import AsyncConnectionPool                      
from dotenv import load_dotenv
import os

load_dotenv()
DATABASE_URL = os.getenv("SQL_DATABASE_URL")

print(DATABASE_URL)

async def get_checkpointer() -> AsyncPostgresSaver:
    pool = AsyncConnectionPool(
        conninfo=DATABASE_URL,
        max_size=20,
        kwargs={"autocommit": True},
        open=False,
    )
    await pool.open()
    checkpointer = AsyncPostgresSaver(pool)
    await checkpointer.setup()
    return checkpointer