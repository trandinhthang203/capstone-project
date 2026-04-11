import yaml
from box import ConfigBox
import os
import json
from langchain_google_genai import ChatGoogleGenerativeAI
from dotenv import load_dotenv
from langchain.messages import HumanMessage, SystemMessage

load_dotenv()
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

_llm = ChatGoogleGenerativeAI(
    api_key=GEMINI_API_KEY,
    model="gemini-2.5-flash",
    temperature=0,
    max_tokens=None,
    timeout=None,
    max_retries=2,
)

def get_response_llm(prompt: str, user_query: str) -> str:
    messages = [
        SystemMessage(content=prompt),
        HumanMessage(content=user_query),
    ]
    return _llm.invoke(messages).content

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

