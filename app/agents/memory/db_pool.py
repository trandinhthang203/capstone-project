from psycopg_pool import AsyncConnectionPool
import os
from dotenv import load_dotenv

load_dotenv()
DATABASE_URL = os.getenv("SQL_DATABASE_URL")

_pool: AsyncConnectionPool | None = None

async def get_pool() -> AsyncConnectionPool:
    global _pool
    if _pool is None:
        _pool = AsyncConnectionPool(
            conninfo=DATABASE_URL,
            min_size=2,       # ← khởi tạo ít connection trước
            max_size=10,      # ← giảm xuống, đủ dùng
            kwargs={"autocommit": True},
            open=False,
        )
        await _pool.open()
    return _pool