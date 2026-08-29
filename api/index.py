from app.main import app as backend_app
from fastapi import FastAPI

app = FastAPI(title="Decision Intelligence API Gateway")
app.mount("/api", backend_app)
