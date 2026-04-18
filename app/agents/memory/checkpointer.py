from langgraph.checkpoint.postgres import PostgresSaver  
from psycopg_pool import ConnectionPool         
from dotenv import load_dotenv
import os

load_dotenv()
DATABASE_URL = os.getenv("SQL_DATABASE_URL")

       

def get_checkpointer() -> PostgresSaver:
    pool = ConnectionPool(
        conninfo=DATABASE_URL,
        max_size=20,
        kwargs={"autocommit": True},
        open=False,
    )
    pool.open()
    checkpointer = PostgresSaver(pool)
    checkpointer.setup()
    return checkpointer
