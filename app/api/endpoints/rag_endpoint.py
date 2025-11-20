from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
import json

from app.services.rag_chain_service import rag_chain_service

router = APIRouter()

class ChatRequest(BaseModel):
    message: str

async def stream_rag_response(chain, message: str):
    docs_sent = False
    async for chunk in chain.astream(message):
        if "answer" in chunk:
            yield f"data: {json.dumps({'type': 'text', 'message': chunk['answer']})}\n\n"
        
        if not docs_sent and "context" in chunk:
            for i, doc in enumerate(chunk["context"]):
                source_message = f"Source {i+1}: {doc.metadata.get('source', 'Unknown')}"
                yield f"data: {json.dumps({'type': 'source', 'message': source_message})}\n\n"
            docs_sent = True

@router.post("/chat")
async def chat(request: ChatRequest):
    chain = rag_chain_service.get_chain()
    return StreamingResponse(stream_rag_response(chain, request.message), media_type="text/event-stream")
