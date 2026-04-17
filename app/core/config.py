import os
from dotenv import load_dotenv
from pydantic_settings import BaseSettings
import yaml
from pathlib import Path

load_dotenv()
BASE_DIR = 'D:/capstone-project/app/prompts'

class Settings(BaseSettings):
    PROJECT_NAME: str = os.getenv('PROJECT_NAME', 'CAPSTONE-PROJECTD')
    SECRET_KEY: str = os.getenv('SECRET_KEY', '')
    API_PREFIX: str = ''
    BACKEND_CORS_ORIGINS: list[str] = ['*']
    DATABASE_URL: str = os.getenv('SQL_DATABASE_URL', '')
    ACCESS_TOKEN_EXPIRE_SECONDS: int = 60 * 60 * 24 * 7
    SECURITY_ALGORITHM: str = 'HS256'


settings = Settings()

# with open(BASE_DIR / 'system_prompts.yaml', 'r', encoding='utf-8') as file:
#     system_prompt = yaml.safe_load(file)

with open(os.path.join(BASE_DIR, 'supervisor_agent.yaml'), 'r', encoding='utf-8') as file:
    supervisor_prompt = yaml.safe_load(file)

__all__ = ['settings', 'supervisor_prompt']