"""Xuất sơ đồ LangGraph của chatbot thành ảnh PNG.

Chạy từ thư mục gốc dự án:
    python -m app.agents.test
    python -m app.agents.test --output artifacts/chatbot_graph.png
"""

from __future__ import annotations

import argparse
import asyncio
from pathlib import Path

from langgraph.checkpoint.memory import MemorySaver

from app.agents.base.graph import create_workflow


async def export_graph(output_path: Path) -> Path:
    """Khởi tạo workflow và ghi biểu đồ Mermaid dưới dạng PNG."""
    # Không cần kết nối PostgreSQL chỉ để render cấu trúc graph.
    workflow = await create_workflow(checkpointer=MemorySaver())
    png_data = workflow.get_graph().draw_mermaid_png()

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(png_data)
    return output_path.resolve()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Xuất sơ đồ LangGraph thành file PNG")
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("workflow_graph.png"),
        help="Đường dẫn file PNG đầu ra (mặc định: workflow_graph.png)",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    output_path = asyncio.run(export_graph(args.output))
    print(f"Đã xuất graph ra: {output_path}")


if __name__ == "__main__":
    main()
