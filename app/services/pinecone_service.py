"""
Pinecone export pipeline for syncing embeddings and metadata.
"""

import os
from typing import List, Dict, Any, Optional
from sqlalchemy.orm import Session
from app.db.models import Embedding, Chunk, Document
from app.db.services import EmbeddingService

try:
    from pinecone import Pinecone, ServerlessSpec
except ImportError:
    Pinecone = None
    ServerlessSpec = None


class PineconeExportService:
    """Service for exporting embeddings and metadata to Pinecone."""

    def __init__(self):
        """Initialize Pinecone client."""
        self.api_key = os.getenv("PINECONE_API_KEY")
        self.environment = os.getenv("PINECONE_ENVIRONMENT", "us-east-1")
        self.index_name = os.getenv("PINECONE_INDEX_NAME", "asktemoc")
        self.client = None
        self.index = None

        if not self.api_key:
            raise ValueError("PINECONE_API_KEY environment variable is required")

        if Pinecone is None:
            raise ImportError("pinecone package not installed")

        self._initialize_client()

    def _initialize_client(self):
        """Initialize Pinecone client and index."""
        self.client = Pinecone(api_key=self.api_key)

        # Check if index exists, create if not
        if self.index_name not in self.client.list_indexes().names():
            self.client.create_index(
                name=self.index_name,
                dimension=1536,  # Default for OpenAI embeddings
                metric="cosine",
                spec=ServerlessSpec(cloud="aws", region=self.environment),
            )
            print(f"Created Pinecone index: {self.index_name}")

        self.index = self.client.Index(self.index_name)

    def prepare_vectors_for_upsert(
        self, db: Session, embeddings: List[Embedding]
    ) -> List[tuple]:
        """
        Prepare vectors and metadata for Pinecone upsert.

        Returns list of tuples: (id, vector, metadata)
        """
        vectors = []

        for embedding in embeddings:
            chunk = db.query(Chunk).filter(Chunk.id == embedding.chunk_id).first()
            if not chunk:
                continue

            document = db.query(Document).filter(
                Document.id == chunk.document_id
            ).first()
            if not document:
                continue

            # Prepare metadata
            metadata = {
                "embedding_id": embedding.id,
                "chunk_id": chunk.id,
                "document_id": document.id,
                "document_title": document.title,
                "document_source": document.source or "",
                "chunk_index": chunk.chunk_index,
                "text": chunk.text,
                "created_at": chunk.created_at.isoformat() if chunk.created_at else "",
            }

            # Add custom metadata from chunk
            if chunk.chunk_metadata:
                metadata.update(chunk.chunk_metadata)

            # Add custom metadata from document
            if document.doc_metadata:
                metadata.update(document.doc_metadata)

            # Use embedding ID as vector ID
            vector_id = embedding.pinecone_id or embedding.id

            vectors.append((vector_id, embedding.vector, metadata))

        return vectors

    def upsert_vectors(self, db: Session, embeddings: List[Embedding]) -> Dict[str, Any]:
        """
        Upsert embeddings and metadata to Pinecone.

        Returns a dictionary with upsert results and statistics.
        """
        if not self.index:
            raise RuntimeError("Pinecone client not initialized")

        vectors = self.prepare_vectors_for_upsert(db, embeddings)

        if not vectors:
            return {"status": "no_vectors", "count": 0}

        try:
            # Upsert vectors to Pinecone
            upsert_response = self.index.upsert(
                vectors=vectors,
                namespace="default",
            )

            # Update sync status in database
            updated_ids = []
            for vector_id, _, _ in vectors:
                # Find embedding by ID or pinecone_id
                embedding = db.query(Embedding).filter(
                    (Embedding.id == vector_id) | (Embedding.pinecone_id == vector_id)
                ).first()
                if embedding:
                    EmbeddingService.mark_synced(db, embedding.id, vector_id)
                    updated_ids.append(embedding.id)

            return {
                "status": "success",
                "upserted_count": len(vectors),
                "updated_db_count": len(updated_ids),
                "pinecone_response": upsert_response,
            }

        except Exception as e:
            return {
                "status": "error",
                "error": str(e),
                "attempted_count": len(vectors),
            }

    def export_document_embeddings(
        self, db: Session, document_id: str
    ) -> Dict[str, Any]:
        """Export all embeddings for a specific document to Pinecone."""
        embeddings = EmbeddingService.get_embeddings_by_document(db, document_id)
        unsynced = [e for e in embeddings if not e.is_synced]

        if not unsynced:
            return {
                "status": "no_new_embeddings",
                "total_embeddings": len(embeddings),
                "synced_embeddings": len([e for e in embeddings if e.is_synced]),
            }

        return self.upsert_vectors(db, unsynced)

    def export_unsynced_embeddings(
        self, db: Session, batch_size: int = 100
    ) -> Dict[str, Any]:
        """Export all unsynced embeddings to Pinecone."""
        unsynced = EmbeddingService.list_unsynced_embeddings(db, limit=batch_size)

        if not unsynced:
            return {
                "status": "no_embeddings",
                "count": 0,
            }

        return self.upsert_vectors(db, unsynced)

    def delete_from_pinecone(
        self, vector_ids: List[str], namespace: str = "default"
    ) -> Dict[str, Any]:
        """Delete vectors from Pinecone by ID."""
        if not self.index:
            raise RuntimeError("Pinecone client not initialized")

        try:
            response = self.index.delete(ids=vector_ids, namespace=namespace)
            return {
                "status": "success",
                "deleted_count": len(vector_ids),
                "response": response,
            }
        except Exception as e:
            return {
                "status": "error",
                "error": str(e),
                "attempted_count": len(vector_ids),
            }

    def search_pinecone(
        self,
        query_vector: List[float],
        top_k: int = 10,
        filters: Optional[Dict[str, Any]] = None,
        namespace: str = "default",
    ) -> Dict[str, Any]:
        """Search Pinecone index."""
        if not self.index:
            raise RuntimeError("Pinecone client not initialized")

        try:
            response = self.index.query(
                vector=query_vector,
                top_k=top_k,
                include_metadata=True,
                filter=filters,
                namespace=namespace,
            )
            return {
                "status": "success",
                "matches": response.get("matches", []),
            }
        except Exception as e:
            return {
                "status": "error",
                "error": str(e),
            }

    def get_index_stats(self) -> Dict[str, Any]:
        """Get statistics about the Pinecone index."""
        if not self.index:
            raise RuntimeError("Pinecone client not initialized")

        try:
            stats = self.index.describe_index_stats()
            return {
                "status": "success",
                "stats": stats,
            }
        except Exception as e:
            return {
                "status": "error",
                "error": str(e),
            }
