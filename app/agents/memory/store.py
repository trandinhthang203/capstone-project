# store.py
from langgraph.store.postgres.aio import AsyncPostgresStore  # ← đổi import
from psycopg_pool import AsyncConnectionPool
import os
from dotenv import load_dotenv

load_dotenv()
DATABASE_URL = os.getenv("SQL_DATABASE_URL")

async def get_store() -> AsyncPostgresStore:
    pool = AsyncConnectionPool(
        conninfo=DATABASE_URL,
        max_size=20,
        kwargs={"autocommit": True},
        open=False,
    )
    await pool.open()
    store = AsyncPostgresStore(pool)
    await store.setup()
    return store