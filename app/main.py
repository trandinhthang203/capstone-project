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
# test_terminal.py

import os
import sys
import asyncio

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT_DIR)
from app.agents.base.utils import set_queue
from app.agents.base.state import StreamEvent
from dotenv import load_dotenv
load_dotenv()

from langchain_core.messages import HumanMessage, AIMessage, AIMessageChunk
from app.agents.base.graph import create_workflow
from app.db.base import Base
from app.db.session import engine
from app.models import Role, User, ChatSession, ChatMessage, Feedback

Base.metadata.create_all(bind=engine)
# ── Config cố định để test ──────────────────────────────────────────────────
SESSION_ID = "test-session-005"   # giữ nguyên để test memory xuyên suốt
USER_ID    = 2

CONFIG = {
    "configurable": {
        "thread_id": SESSION_ID,
        "user_id":   USER_ID,
    }
}
# ───────────────────────────────────────────────────────────────────────────


# test_chat.py — sửa hàm chat
async def chat(app, history: list, user_input: str) -> str:
    history.append(HumanMessage(content=user_input))

    queue = asyncio.Queue()
    set_queue(queue)

    print("\n\033[94mAssistant:\033[0m ", end="", flush=True)

    full_response = ""

    graph_task = asyncio.create_task(
        app.ainvoke(
            {
                "messages": [HumanMessage(content=user_input)],
                "user_id": USER_ID,
                "user_input": user_input, 
            },
            CONFIG,
        )
    )

    while not graph_task.done() or not queue.empty():
        try:
            event: StreamEvent = await asyncio.wait_for(queue.get(), timeout=0.05)
        except asyncio.TimeoutError:
            continue

        if event.type == "progress":
            print(f"\n\033[93m⏳ [{event.node}] {event.message}\033[0m", flush=True)

        elif event.type == "result":
            print(f"\n\033[92m✅ [{event.node}] {event.message}\033[0m", flush=True)
            if event.data and "answer" in event.data and event.data["answer"]:
                full_response = event.data["answer"]

        elif event.type == "error":
            print(f"\n\033[91m❌ [{event.node}] {event.message}\033[0m", flush=True)

    result = await graph_task

    if not full_response:
        full_response = result.get("final_response", "") or ""

    print()
    history.append(AIMessage(content=full_response))
    return full_response



async def main():
    print("⏳ Đang khởi tạo workflow...")
    app = await create_workflow()
    print(f"✅ Sẵn sàng!  (session={SESSION_ID}, user={USER_ID})")
    print("💡 Gõ 'quit' hoặc 'exit' để thoát | 'clear' để reset history local\n")

    history: list = []

    while True:
        try:
            user_input = input("\033[92mBạn:\033[0m ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n👋 Tạm biệt!")
            break

        if not user_input:
            continue

        if user_input.lower() in {"quit", "exit"}:
            print("👋 Tạm biệt!")
            break

        if user_input.lower() == "clear":
            history.clear()
            print("🗑️  Đã xoá history local (memory trên DB vẫn giữ nguyên)")
            continue

        if user_input.lower() == "history":
            if not history:
                print("  (chưa có tin nhắn nào)")
            for msg in history:
                role = "Bạn" if isinstance(msg, HumanMessage) else "AI"
                print(f"  [{role}] {msg.content[:120]}{'...' if len(msg.content) > 120 else ''}")
            continue

        try:
            await chat(app, history, user_input)
        except Exception as e:
            print(f"\n❌ Lỗi: {e}")


if __name__ == "__main__":
    import selectors
    asyncio.run(main(), loop_factory=lambda: asyncio.SelectorEventLoop(selectors.SelectSelector()))