"""Ví dụ tối giản: LangGraph interrupt + FastAPI resume.

Chạy độc lập:
    uvicorn app.agents.test:app --reload --port 8001

Luồng xử lý:
    prepare_order -> human_approval (tạm dừng) -> execute_order

Thử nhanh:
    1. POST /orders
       body: {"item": "Laptop", "quantity": 2}
    2. Lấy ``thread_id`` trong response.
    3. POST /orders/{thread_id}/resume
       body: {"approved": true, "note": "Đồng ý mua"}

MemorySaver chỉ lưu checkpoint trong RAM, phù hợp để học/demo. Khi chạy thật,
hãy thay bằng checkpointer bền vững (ví dụ PostgresSaver).
"""

from typing import Any, TypedDict
from uuid import uuid4

from fastapi import FastAPI, HTTPException
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt
from pydantic import BaseModel, Field


class OrderState(TypedDict, total=False):
    item: str
    quantity: int
    total: int
    approved: bool
    reviewer_note: str
    result: str


def prepare_order(state: OrderState) -> OrderState:
    """Tính tiền trước khi xin người dùng xác nhận."""
    unit_price = 100_000
    return {"total": state["quantity"] * unit_price}


def human_approval(state: OrderState) -> OrderState:
    """Dừng graph và chờ dữ liệu từ endpoint /resume.

    Khi resume, node này được chạy lại từ đầu. Lúc đó ``interrupt()`` không dừng
    nữa mà trả về chính giá trị được gửi bởi ``Command(resume=...)``.
    """
    answer = interrupt(
        {
            "question": "Bạn có đồng ý duyệt đơn hàng này không?",
            "order": {
                "item": state["item"],
                "quantity": state["quantity"],
                "total": state["total"],
            },
            "expected_resume": {
                "approved": "boolean",
                "note": "string (không bắt buộc)",
            },
        }
    )

    # answer chính là dict được gửi vào Command(resume=answer).
    return {
        "approved": bool(answer.get("approved", False)),
        "reviewer_note": str(answer.get("note", "")),
    }


def execute_order(state: OrderState) -> OrderState:
    """Chạy sau khi đã nhận quyết định của người dùng."""
    if state["approved"]:
        result = f"Đã tạo đơn {state['quantity']} x {state['item']}."
    else:
        result = f"Đơn {state['item']} đã bị từ chối."
    return {"result": result}


def build_graph():
    builder = StateGraph(OrderState)
    builder.add_node("prepare_order", prepare_order)
    builder.add_node("human_approval", human_approval)
    builder.add_node("execute_order", execute_order)
    builder.add_edge(START, "prepare_order")
    builder.add_edge("prepare_order", "human_approval")
    builder.add_edge("human_approval", "execute_order")
    builder.add_edge("execute_order", END)

    # Interrupt chỉ có thể resume khi graph có checkpointer.
    return builder.compile(checkpointer=MemorySaver())


graph = build_graph()
app = FastAPI(title="LangGraph Interrupt Demo")


class CreateOrderRequest(BaseModel):
    item: str = Field(min_length=1, examples=["Laptop"])
    quantity: int = Field(gt=0, examples=[2])


class ResumeRequest(BaseModel):
    approved: bool
    note: str = ""


def graph_config(thread_id: str) -> dict[str, dict[str, str]]:
    """thread_id là khóa để checkpointer tìm đúng lần chạy đang tạm dừng."""
    return {"configurable": {"thread_id": thread_id}}


def format_result(thread_id: str, result: dict[str, Any]) -> dict[str, Any]:
    """Đổi kết quả LangGraph thành response dễ đọc cho client."""
    interrupts = result.get("__interrupt__", ())
    if interrupts:
        first = interrupts[0]
        payload = first.value if hasattr(first, "value") else first
        return {
            "thread_id": thread_id,
            "status": "waiting_for_human",
            "interrupt": payload,
        }

    return {
        "thread_id": thread_id,
        "status": "completed",
        "state": result,
    }


@app.post("/orders")
async def create_order(data: CreateOrderRequest) -> dict[str, Any]:
    """Bắt đầu graph; response sẽ dừng tại node human_approval."""
    thread_id = str(uuid4())
    result = await graph.ainvoke(
        {"item": data.item, "quantity": data.quantity},
        config=graph_config(thread_id),
    )
    return format_result(thread_id, result)


@app.post("/orders/{thread_id}/resume")
async def resume_order(thread_id: str, data: ResumeRequest) -> dict[str, Any]:
    """Tiếp tục đúng graph đang dừng bằng thread_id của request đầu tiên."""
    config = graph_config(thread_id)
    snapshot = await graph.aget_state(config)

    if not snapshot.values:
        raise HTTPException(status_code=404, detail="Không tìm thấy thread_id")
    if not snapshot.next:
        raise HTTPException(status_code=409, detail="Graph này đã hoàn thành")

    result = await graph.ainvoke(
        Command(resume={"approved": data.approved, "note": data.note}),
        config=config,
    )
    return format_result(thread_id, result)


@app.get("/orders/{thread_id}")
async def get_order_state(thread_id: str) -> dict[str, Any]:
    """Xem checkpoint hiện tại để quan sát graph đang chờ hay đã xong."""
    snapshot = await graph.aget_state(graph_config(thread_id))
    if not snapshot.values:
        raise HTTPException(status_code=404, detail="Không tìm thấy thread_id")
    return {
        "thread_id": thread_id,
        "status": "waiting_for_human" if snapshot.next else "completed",
        "next_nodes": list(snapshot.next),
        "state": snapshot.values,
    }
