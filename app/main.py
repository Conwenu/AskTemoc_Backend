from fastapi import FastAPI
from app.api.endpoints import query, documents, pinecone, dashboard, rag_endpoint
from app.db.database import init_db

app = FastAPI(title="AskTemoc Backend")

# Initialize database on startup
@app.on_event("startup")
def startup_event():
    init_db()

# Include routers
app.include_router(query.router, prefix="/api/query", tags=['query'])
app.include_router(documents.router, prefix="/api", tags=['documents'])
app.include_router(pinecone.router, prefix="/api", tags=['pinecone'])
app.include_router(dashboard.router, prefix="/api", tags=['dashboard'])
app.include_router(rag_endpoint.router, prefix="/api", tags=['rag'])