# from fastapi import FastAPI
# import uvicorn
# app = FastAPI()

# @app.get("/")
# def health_check():
#     return {
#         "status": 200,
#         "notifi": "OKE"
#     }

# if __name__ == "__main__":
#     uvicorn.run(
#       "app.main:app",
#       host="127.0.0.1",
#       port=8000,
#       reload=True
#     )

from app.db.session import get_db
from scripts.models.procedure import Thu_Tuc
from scripts.models.method import Cach_Thuc_Thuc_Hien
from scripts.models.component import Thanh_Phan_Ho_So
from scripts.models.basis import Can_Cu_Phap_Ly

from langchain_google_genai import ChatGoogleGenerativeAI
from langchain.messages import HumanMessage, SystemMessage
import os
from dotenv import load_dotenv
from app.core.config import *
from sqlalchemy import text
import json
from app.helpers.utils.common import get_response_llm

load_dotenv()

from app.agents.base.graph import app
# main.py

result = app.invoke({
    "user_input": "Tôi muốn biết chi tiết tất cả các thông tin của thủ tục đăng ký tạm trú?",
    "messages": [],
    "session_id": "test-001",
    "procedures": [],
    "pipeline": [],
    "current_agent": "",
    "next_agent": "",
    "qa_output": None,
    "forms_output": None,
    "location_output": None,
    "error": None,
    "final_response": None,
})

print(result["final_response"])