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

from dotenv import load_dotenv
load_dotenv()

from langchain_core.messages import HumanMessage, AIMessage, AIMessageChunk
from app.agents.base.graph import create_workflow

# ── Config cố định để test ──────────────────────────────────────────────────
SESSION_ID = "test-session-001"   # giữ nguyên để test memory xuyên suốt
USER_ID    = "test-user-001"

CONFIG = {
    "configurable": {
        "thread_id": SESSION_ID,
        "user_id":   USER_ID,
    }
}
# ───────────────────────────────────────────────────────────────────────────


async def chat(app, history: list, user_input: str) -> str:
    """Gửi tin nhắn, stream response ra terminal, trả về nội dung đầy đủ."""
    history.append(HumanMessage(content=user_input))

    

    print("\n\033[94mAssistant:\033[0m ", end="", flush=True)

    full_response = ""

    async for event in app.astream_events(
        {
            "messages": [HumanMessage(content=user_input)],
            "user_id": USER_ID,
        },
        CONFIG,
        version="v2",
    ):
        if event["event"] == "on_chat_model_stream":
            chunk = event["data"]["chunk"]
            if isinstance(chunk, AIMessageChunk) and chunk.content:
                print(chunk.content, end="", flush=True)
                full_response += chunk.content

    print()  # xuống dòng sau khi stream xong

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