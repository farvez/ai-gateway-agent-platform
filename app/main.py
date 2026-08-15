from fastapi import FastAPI

app = FastAPI(
    title="AI Gateway Agent Platform",
    version="0.1.0"
)

@app.get("/")
def root():
    return {
        "message": "Ai gateway Agent Platform is running"
    }

@app.get("/health")
def health():
    return {
        "status": "healthy"
    }