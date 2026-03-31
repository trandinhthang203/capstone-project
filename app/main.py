from fastapi import FastAPI
import uvicorn
app = FastAPI()

@app.get("/")
def health_check():
    return {
        "status": 200,
        "notifi": "OKE"
    }

if __name__ == "__main__":
    uvicorn.run(
      "app.main:app",
      host="127.0.0.1",
      port=8000,
      reload=True
    )