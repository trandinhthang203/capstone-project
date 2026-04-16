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
import sys
import os

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT_DIR)

from scripts.models.procedure import Thu_Tuc
from scripts.models.method import Cach_Thuc_Thuc_Hien
from scripts.models.component import Thanh_Phan_Ho_So
from scripts.models.basis import Can_Cu_Phap_Ly
from dotenv import load_dotenv
from app.core.config import *
import chainlit as cl
from langchain_core.messages import HumanMessage, AIMessageChunk

from app.agents.base.graph import app
load_dotenv()

# main.py

# from langsmith import traceable

# @traceable
# def run():
#     result = app.invoke({
#         "user_input": "lệ phí làm lại thẻ căn cước công dân là bao nhiêu?",
#         "messages": [],
#         "session_id": "test-001",
#         "procedures": [],
#         "pipeline": [],
#         "current_agent": "",
#         "next_agent": "",
#         "qa_output": None,
#         "forms_output": None,
#         "location_output": None,
#         "error": None,
#         "final_response": None,
#     })

#     print(result["final_response"])

# if __name__ == "__main__":
#     run()

@cl.on_chat_start
async def on_chat_start():
    # Lưu lịch sử hội thoại vào session
    cl.user_session.set("history", [])
    await cl.Message(content="Xin chào! Tôi có thể giúp gì cho bạn?").send()

# ✅ Chạy mỗi khi user gửi tin nhắn
@cl.on_message
async def on_message(message: cl.Message):
    history = cl.user_session.get("history")
    
    # Thêm tin nhắn user vào history
    history.append(HumanMessage(content=str(message.content)))
    
    # Tạo message placeholder để stream response
    msg = cl.Message(content="")
    await msg.send()
    
    # Stream output từ LangGraph
    async for event in app.astream_events(
        {
        "user_input": message.content,
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
    },
        version="v2"
    ):
        kind = event["event"]
        
        # Bắt token streaming từ LLM
        if kind == "on_chat_model_stream":
            chunk = event["data"]["chunk"]
            if isinstance(chunk, AIMessageChunk) and chunk.content:
                await msg.stream_token(chunk.content)
    
    # Finalize message
    await msg.update()
    
    # Lưu response vào history
    from langchain_core.messages import AIMessage
    history.append(AIMessage(content=msg.content))
    cl.user_session.set("history", history)