from langgraph.store.postgres.aio import AsyncPostgresStore
from app.agents.memory.db_pool import get_pool

async def get_store() -> AsyncPostgresStore:
    pool = await get_pool()          
    store = AsyncPostgresStore(pool)
    await store.setup()
    return store