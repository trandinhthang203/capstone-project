from langgraph.graph import END
import json

def get_next_agent(pipeline: list[str], current_agent: str) -> str | list[str]:
    
    try:
        if current_agent not in pipeline:
            return END
        
        for i, step in enumerate(pipeline):
            if step == current_agent:
                return pipeline[i + 1]

    except(Exception) as e:
        return END
    
def format_context(rows, columns) -> str:
    data = [dict(zip(columns, row)) for row in rows]
    return json.dumps(data, ensure_ascii=False, indent=2)
