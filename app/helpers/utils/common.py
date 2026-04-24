import yaml
from box import ConfigBox
import os
import json
# from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_groq import ChatGroq
from dotenv import load_dotenv
from langchain.messages import HumanMessage, SystemMessage, AnyMessage
import asyncio

load_dotenv()
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
# GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

_llm = ChatGroq(
    api_key=GROQ_API_KEY,
    model="openai/gpt-oss-120b",
    temperature=0,
    max_tokens=None,
    timeout=None,
    max_retries=5,
)

async def get_response_llm(prompt: str, messages: list[AnyMessage]) -> str:
    response = await asyncio.to_thread(
        _llm.invoke,
        [SystemMessage(content=prompt), *messages]
    )
    return response.content

def read_yaml():
    base_dir = os.path.dirname(os.path.abspath(__file__))
    config_path = os.path.join(base_dir, "config.yaml")
    
    with open(config_path, "r", encoding="utf-8") as f:
        content = yaml.safe_load(f)
        return ConfigBox(content)

def read_json(base_url, file_name):
    file_path = os.path.join(base_url, file_name)
    with open(file_path, "r", encoding="utf-8") as file:
        data = json.load(file)
        return data