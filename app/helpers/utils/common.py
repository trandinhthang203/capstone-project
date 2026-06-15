import yaml
from box import ConfigBox
import os
import json
from langchain_google_genai import ChatGoogleGenerativeAI
from dotenv import load_dotenv
from langchain.messages import HumanMessage, SystemMessage, AnyMessage
import asyncio


load_dotenv()
# GROQ_API_KEY = os.getenv("GROQ_API_KEY")
# os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = r"D:\capstone-project\location-498221-9b453abda182.json"
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

_llm = ChatGoogleGenerativeAI(
    model="gemini-2.5-flash",
    google_api_key=GEMINI_API_KEY,
    temperature=0, 
    max_tokens=None,
    timeout=None,
    max_retries=5,
)
# print(model.invoke("kể 1 câu chuyện hài"))

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