"""
FastAPI endpoints for Pinecone export operations.
"""

from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.db.services import EmbeddingService, DocumentService
from app.services.pinecone_service import PineconeExportService
from app.schemas.db_schemas import PineconeExportResponse, PineconeIndexStats

router = APIRouter(prefix="/pinecone", tags=["pinecone"])


def get_pinecone_service():
    """Dependency to get PineconeExportService."""
    try:
        return PineconeExportService()
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to initialize Pinecone service: {str(e)}",
        )


@router.post("/export/document/{doc_id}", response_model=PineconeExportResponse)
def export_document_embeddings(
    doc_id: str,
    db: Session = Depends(get_db),
    pinecone_svc: PineconeExportService = Depends(get_pinecone_service),
):
    """Export all embeddings for a specific document to Pinecone."""
    document = DocumentService.get_document(db=db, doc_id=doc_id)
    if not document:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Document not found"
        )

    result = pinecone_svc.export_document_embeddings(db=db, document_id=doc_id)

    if result.get("status") == "error":
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=result.get("error"),
        )

    return PineconeExportResponse(
        status=result.get("status"),
        message=f"Exported {result.get('upserted_count', 0)} embeddings",
        upserted_count=result.get("upserted_count"),
        updated_db_count=result.get("updated_db_count"),
    )


@router.post("/export/unsynced", response_model=PineconeExportResponse)
def export_unsynced_embeddings(
    batch_size: int = 100,
    db: Session = Depends(get_db),
    pinecone_svc: PineconeExportService = Depends(get_pinecone_service),
):
    """Export all unsynced embeddings to Pinecone."""
    result = pinecone_svc.export_unsynced_embeddings(db=db, batch_size=batch_size)

    if result.get("status") == "error":
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=result.get("error"),
        )

    return PineconeExportResponse(
        status=result.get("status"),
        message=f"Exported {result.get('upserted_count', 0)} embeddings",
        upserted_count=result.get("upserted_count"),
        updated_db_count=result.get("updated_db_count"),
    )


@router.post("/export/batch", response_model=PineconeExportResponse)
def export_batch_embeddings(
    embedding_ids: List[str],
    db: Session = Depends(get_db),
    pinecone_svc: PineconeExportService = Depends(get_pinecone_service),
):
    """Export a batch of specific embeddings to Pinecone."""
    embeddings = EmbeddingService.get_embeddings_by_ids(db=db, embedding_ids=embedding_ids)

    if not embeddings:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="No embeddings found"
        )

    result = pinecone_svc.upsert_vectors(db=db, embeddings=embeddings)

    if result.get("status") == "error":
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=result.get("error"),
        )

    return PineconeExportResponse(
        status=result.get("status"),
        message=f"Exported {result.get('upserted_count', 0)} embeddings",
        upserted_count=result.get("upserted_count"),
        updated_db_count=result.get("updated_db_count"),
    )


@router.delete("/vectors", response_model=PineconeExportResponse)
def delete_vectors_from_pinecone(
    vector_ids: List[str],
    pinecone_svc: PineconeExportService = Depends(get_pinecone_service),
):
    """Delete vectors from Pinecone."""
    if not vector_ids:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="No vector IDs provided"
        )

    result = pinecone_svc.delete_from_pinecone(vector_ids=vector_ids)

    if result.get("status") == "error":
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=result.get("error"),
        )

    return PineconeExportResponse(
        status=result.get("status"),
        message=f"Deleted {result.get('deleted_count', 0)} vectors",
    )


@router.get("/index/stats", response_model=PineconeIndexStats)
def get_index_statistics(
    pinecone_svc: PineconeExportService = Depends(get_pinecone_service),
):
    """Get Pinecone index statistics."""
    result = pinecone_svc.get_index_stats()

    if result.get("status") == "error":
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=result.get("error"),
        )

    return PineconeIndexStats(
        status=result.get("status"),
        stats=result.get("stats"),
    )


@router.get("/search", response_model=dict)
def search_pinecone(
    query_vector: List[float],
    top_k: int = 10,
    db: Session = Depends(get_db),
    pinecone_svc: PineconeExportService = Depends(get_pinecone_service),
):
    """Search Pinecone index with query vector."""
    if not query_vector:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Query vector required"
        )

    result = pinecone_svc.search_pinecone(query_vector=query_vector, top_k=top_k)

    if result.get("status") == "error":
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=result.get("error"),
        )

    return result
