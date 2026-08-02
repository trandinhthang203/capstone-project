import uvicorn
from fastapi import FastAPI
from fastapi_sqlalchemy import DBSessionMiddleware
from starlette.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
from app.api.api_router import router
from app.db.base import Base
from app.db.session import engine
from app.core.config import settings
from app.helpers.utils.exception import CustomException
from app.helpers.utils.init_embedding import _get_client, _get_models
from app.agents.base.graph import create_workflow

@asynccontextmanager
async def lifespan(app: FastAPI):
    _get_client()
    _get_models()
    app.state.workflow = await create_workflow()
    yield


# logging.config.fileConfig(settings.LOGGING_CONFIG_FILE, disable_existing_loggers=False)
# Base.metadata.create_all(bind=engine)


def get_application() -> FastAPI:
    application = FastAPI(
        title=settings.PROJECT_NAME, docs_url="/docs", redoc_url='/re-docs',
        openapi_url=f"{settings.API_PREFIX}/openapi.json",
        lifespan=lifespan,
        description='''
        Multi-agent system for supporting administrative procedures:
            - Intelligent routing and task handling
            - Q&A over legal knowledge (RAG)
            - Workflow guidance for procedures
        '''
    )
    application.add_middleware(
        CORSMiddleware,
        allow_origins=[str(origin) for origin in settings.BACKEND_CORS_ORIGINS],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    # application.add_middleware(DBSessionMiddleware, db_url=settings.DATABASE_URL)
    application.include_router(router, prefix=settings.API_PREFIX)
    # application.add_exception_handler(CustomException, http_exception_handler)

    return application


app = get_application()
if __name__ == '__main__':
    uvicorn.run("app.main:app", host="127.0.0.1", port=8000, reload=True)
