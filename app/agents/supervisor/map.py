from langchain_google_genai import ChatGoogleGenerativeAI

llm = ChatGoogleGenerativeAI(
    model="gemini-2.5-flash",
    temperature=0.7,
)

# sk-bee-aa414c7f020189f645ed4d6056009a465f08570305b3bb25f71f4dbdf3af2ad9

# Gọi đồng bộ
response = llm.invoke("Xin chào, bạn là ai?")
print(response.content)