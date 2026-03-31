import os
from dotenv import load_dotenv
from pydantic import BaseModel

load_dotenv()

class Settings(BaseModel):
    PROJECT_NAME = os.getenv('PROJECT_NAME', 'CAPSTONE-PROJECTD')
    SECRET_KEY = os.getenv('SECRET_KEY', '')
    API_PREFIX = ''
    BACKEND_CORS_ORIGINS = ['*']
    DATABASE_URL = os.getenv('SQL_DATABASE_URL', '')
    ACCESS_TOKEN_EXPIRE_SECONDS: int = 60 * 60 * 24 * 7 
    SECURITY_ALGORITHM = 'HS256'


settings = Settings()