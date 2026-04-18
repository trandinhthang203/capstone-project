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
# main.py
import os
import sys

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT_DIR)

from dotenv import load_dotenv
load_dotenv()

from app.core.config import *
import chainlit as cl
from langchain_core.messages import HumanMessage, AIMessage, AIMessageChunk
from app.agents.base.graph import create_workflow

@cl.on_chat_start
async def on_chat_start():
    # Khởi tạo workflow app 1 lần cho mỗi session
    workflow_app = create_workflow()
    
    # Lấy session_id và user_id (có thể lấy từ cl.user_session hoặc hardcode khi test)
    session_id = cl.user_session.get("id")  # Chainlit tự tạo session id
    user_id = cl.user_session.get("user_id", "anonymous")

    cl.user_session.set("app", workflow_app)
    cl.user_session.set("history", [])
    cl.user_session.set("config", {
        "configurable": {
            "thread_id": session_id,
            "user_id": user_id,
        }
    })

    await cl.Message(content="Xin chào! Tôi có thể giúp gì cho bạn?").send()


@cl.on_message
async def on_message(message: cl.Message):
    workflow_app = cl.user_session.get("app")
    config = cl.user_session.get("config")
    history = cl.user_session.get("history")

    history.append(HumanMessage(content=str(message.content)))

    msg = cl.Message(content="")
    await msg.send()

    async for event in workflow_app.astream_events(
        {
            "messages": history,      
            "user_id": cl.user_session.get("user_id", "anonymous"),
        },
        config,
        version="v2"                 
    ):
        kind = event["event"]

        if kind == "on_chat_model_stream":
            chunk = event["data"]["chunk"]
            if isinstance(chunk, AIMessageChunk) and chunk.content:
                await msg.stream_token(chunk.content)

    await msg.update()

    history.append(AIMessage(content=msg.content))
    cl.user_session.set("history", history)