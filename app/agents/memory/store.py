import os
from dotenv import load_dotenv
from langgraph.store.postgres import PostgresStore      
from psycopg_pool import ConnectionPool    
load_dotenv()
DATABASE_URL = os.getenv("SQL_DATABASE_URL")            

def get_store() -> PostgresStore:
    pool = ConnectionPool(
        conninfo=DATABASE_URL,
        max_size=20,
        kwargs={"autocommit": True},
        open=False,
    )
    pool.open()
    store = PostgresStore(pool)
    store.setup()
    return store
