from fastapi import FastAPI
from app.api.routes import router

app = FastAPI(title="CortexFlow AI API")

app.include_router(router)