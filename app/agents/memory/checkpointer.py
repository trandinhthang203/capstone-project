# checkpointer.py
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver  
from app.agents.memory.db_pool import get_pool

async def get_checkpointer() -> AsyncPostgresSaver:
    pool = await get_pool()        
    checkpointer = AsyncPostgresSaver(pool)
    await checkpointer.setup()
    return checkpointer