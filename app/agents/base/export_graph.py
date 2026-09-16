import asyncio
import selectors
from app.agents.base.graph import create_workflow

async def export_graph():
    app = await create_workflow()
    png_bytes = app.get_graph(xray=True).draw_mermaid_png()

    with open("workflow_graph.png", "wb") as f:
        f.write(png_bytes)
    print("Đã lưu workflow_graph.png")

if __name__ == "__main__":
    asyncio.run(
        export_graph(),
        loop_factory=lambda: asyncio.SelectorEventLoop(selectors.SelectSelector())
    )