from langchain_community.utilities import SQLDatabase
from langchain_classic.chains import create_sql_query_chain
from langchain_community.tools.sql_database.tool import QuerySQLDataBaseTool
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import PromptTemplate
from langchain_core.runnables import RunnablePassthrough
import os
from dotenv import load_dotenv

load_dotenv()

# os.environ["OPENAI_API_KEY"] = "sk-..."

# # Kết nối PostgreSQL
# DB_URL = "postgresql+psycopg2://postgres:password@localhost:5432/shop_db"
db = SQLDatabase.from_uri(os.getenv("SQL_DATABASE_URL"))

# # Kiểm tra kết nối
# print("Tables:", db.get_usable_table_names())
# print("Schema:\n", db.get_table_info())

# LLM
llm = ChatGoogleGenerativeAI(api_key=os.getenv("GEMINI_API_KEY"), model = "gemini-2.5-flash", temperature=0)

# Tạo chain sinh SQL
sql_chain = create_sql_query_chain(llm, db)

# Tool thực thi SQL
execute_query = QuerySQLDataBaseTool(db=db)

# Prompt tổng hợp câu trả lời
answer_prompt = PromptTemplate.from_template(
    """Dựa vào câu hỏi, câu SQL đã dùng và kết quả từ database, hãy trả lời bằng tiếng Việt một cách tự nhiên.

Câu hỏi: {question}
SQL đã dùng: {query}
Kết quả SQL: {result}

Câu trả lời:"""
)

# Kết hợp thành pipeline hoàn chỉnh
chain = (
    RunnablePassthrough.assign(query=sql_chain)
    .assign(result=lambda x: execute_query.invoke(x["query"]))
    | answer_prompt
    | llm
    | StrOutputParser()
)

# Chạy thử
questions = [
    "Trình tự thực hiện thủ tục cấp lại CCCD?",
    # "Tổng doanh thu trong tháng 2 năm 2024 là bao nhiêu?",
    # "Danh mục Electronics có bao nhiêu sản phẩm?",
    # "Top 3 sản phẩm có số lượng tồn kho nhiều nhất?",
]

for q in questions:
    print(f"\n❓ {q}")
    answer = chain.invoke({"question": q})
    print(f"💬 {answer}")