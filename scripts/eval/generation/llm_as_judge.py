
from app.helpers.utils.common import _llm
# pyrefly: ignore [missing-import]
from pydantic import BaseModel, Field
from scripts.eval.generation.build_dataset import dataset_name

# Khởi tạo model giám khảo
class EvalResult(BaseModel):
    score: int = Field(description="Điểm số (0 hoặc 1)")
    reasoning: str = Field(description="Giải thích ngắn gọn lý do tại sao cho điểm này")

judge_llm = _llm.with_structured_output(EvalResult)

def faithfulness_evaluator(run, example) -> dict:
    """Đánh giá Faithfulness (Groundedness): Câu trả lời có bịa đặt (hallucinate) thông tin không."""
    context = run.inputs["context"]
    answer = run.outputs["answer"]
    
    prompt = f"""Bạn là một chuyên gia đánh giá thủ tục hành chính.
Nhiệm vụ: Câu trả lời có ĐƯỢC CHỨNG MINH hoàn toàn bởi Ngữ cảnh không?
Nếu Câu trả lời chứa thông tin bịa đặt hoặc quy định pháp lý không có trong Ngữ cảnh, điểm = 0. Nếu hoàn toàn bám sát Ngữ cảnh, điểm = 1.

Ngữ cảnh: {context}
Câu trả lời: {answer}"""
    
    result = judge_llm.invoke(prompt)
    return {"key": "Faithfulness", "score": result.score, "comment": result.reasoning}

def relevance_evaluator(run, example) -> dict:
    """Đánh giá Answer Relevance: Tính hữu ích và đi vào trọng tâm của câu trả lời."""
    question = run.inputs["question"]
    answer = run.outputs["answer"]
    
    prompt = f"""Nhiệm vụ: Câu trả lời có giải quyết trực tiếp Câu hỏi không?
Nếu trả lời lan man, lạc đề hoặc không giải đáp đúng thắc mắc của người dân, điểm = 0. Nếu đi thẳng vào trọng tâm, điểm = 1.

Câu hỏi: {question}
Câu trả lời: {answer}"""
    
    result = judge_llm.invoke(prompt)
    return {"key": "Answer Relevance", "score": result.score, "comment": result.reasoning}

def correctness_evaluator(run, example) -> dict:
    """Đánh giá Correctness: So sánh mức độ chuẩn xác với Ground Truth."""
    answer = run.outputs["answer"]
    ground_truth = example.outputs["ground_truth"]
    
    prompt = f"""Nhiệm vụ: Đánh giá độ chính xác của Câu trả lời so với Đáp án chuẩn.
Nếu sai lệch về mặt ý nghĩa pháp lý, thời gian, cơ quan xử lý hoặc thiếu thông tin quan trọng, điểm = 0. Nếu đồng nghĩa và cung cấp đầy đủ thông tin, điểm = 1.

Đáp án chuẩn: {ground_truth}
Câu trả lời: {answer}"""
    
    result = judge_llm.invoke(prompt)
    return {"key": "Correctness", "score": result.score, "comment": result.reasoning}

# pyrefly: ignore [missing-import]
from langsmith.evaluation import evaluate

# Target function giả lập bước sinh văn bản của bạn
def generation_step(inputs: dict) -> dict:
    question = inputs["question"]
    context = inputs["context"]
    
    # Ở đây, bạn tích hợp LLM Chain/Agent thực tế của hệ thống
    # response = my_generation_chain.invoke({"question": question, "context": context})
    # return {"answer": response.content}
    
    # Code mô phỏng:
    # return {"answer": "Bạn có thể nộp hồ sơ trực tiếp tại Bộ phận Một cửa của UBND cấp xã/phường."}

# Thực thi đánh giá
experiment_results = evaluate(
    generation_step,
    data=dataset_name,
    evaluators=[
        faithfulness_evaluator,
        relevance_evaluator,
        correctness_evaluator
    ],
    experiment_prefix="Gen-Evaluation-Mini",
    metadata={"component": "generation_only"}
)