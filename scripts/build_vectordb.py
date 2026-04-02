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

load_dotenv()

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

def get_response_llm(prompt: str, user_query: str):
    llm = ChatGoogleGenerativeAI(
        api_key = GEMINI_API_KEY,
        model="gemini-2.5-flash",
        temperature=0,
        max_tokens=None,
        timeout=None,
        max_retries=2,
    )
    messages = [
        SystemMessage(content = prompt),
        HumanMessage(content = user_query)
    ]
    response = llm.invoke(messages)
    return response.content


db = next(get_db())
# procedures = db.query(Thu_Tuc).first()
# print(procedures.ten_thu_tuc)


def format_context(rows, columns) -> str:
    data = [dict(zip(columns, row)) for row in rows]
    return json.dumps(data, ensure_ascii=False, indent=2)

def gen_context(user_query: str):
    intent_prompt = example_prompt["INTENT_EXTRACTION"].format(query=user_query)
    procedure_names = get_response_llm(intent_prompt, user_query)

    sql_prompt = example_prompt["SQL_GENERATION"].format(
        procedure_names=procedure_names[0],
        query=user_query
    )
    sql_query = get_response_llm(sql_prompt, user_query)
    results = db.execute(text(sql_query))
    rows = results.fetchall()
    columns = results.keys()

    context = format_context(rows, columns)
    print(f"Độ dài context: {len(context)} ký tự")

    answer_prompt = example_prompt["ANSWER_GENERATION"].format(
        query=user_query,
        context=context,
        link=None
    )

    answer = get_response_llm(answer_prompt, user_query)
    return answer

print(gen_context("Cấp lại thẻ căn cước thực hiện tại cấp tỉnh và cấp trung ương khác nhau thế nào?"))