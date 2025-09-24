from fastapi import FastAPI
from app.api.endpoints import query

app = FastAPI(title="AskTemoc Backend")

app.include_router(query.router, prefix="/api/query", tags=['query'])