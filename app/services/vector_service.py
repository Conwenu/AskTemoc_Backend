import os
from typing import List, Dict, Any, Optional
from langchain_chroma import Chroma
from langchain_ollama import OllamaEmbeddings
from langchain_core.documents import Document


class VectorService:
    def __init__(self, persist_directory: str = "./db/chroma"):
        """
        Initialize VectorService with Chroma vector store and Ollama embeddings.
        
        Args:
            persist_directory: Directory to persist Chroma collections
        """
        self.persist_directory = persist_directory
        self.embedding_function: Optional[OllamaEmbeddings] = None
        self._vector_stores: Dict[str, Chroma] = {}
        
    async def embed(self):
        """
        Initialize Ollama bge-m3 embedding model.
        LangChain has an embedding wrapper for Ollama models.
        """
        if self.embedding_function is None:
            self.embedding_function = OllamaEmbeddings(model="bge-m3")
        return self.embedding_function

    def _get_vector_store(self, collection_name: str) -> Chroma:
        """
        Get or create a Chroma vector store for the given collection.
        
        Args:
            collection_name: Name of the collection
            
        Returns:
            Chroma vector store instance
        """
        if collection_name not in self._vector_stores:
            if self.embedding_function is None:
                raise ValueError("Embedding function not initialized. Call embed() first.")
            
            self._vector_stores[collection_name] = Chroma(
                collection_name=collection_name,
                embedding_function=self.embedding_function,
                persist_directory=self.persist_directory
            )
        return self._vector_stores[collection_name]

    async def add(self, documents: List[str], metadata: Optional[List[Dict[str, Any]]] = None, collection: str = "default"):
        """
        Add documents to the vector store.
        
        Args:
            documents: List of document texts to add
            metadata: Optional list of metadata dicts (one per document). 
                     If None, empty metadata will be used for all documents.
                     If a single dict is provided, it will be applied to all documents.
            collection: Collection name to add documents to
            
        Raises:
            ValueError: If embedding function is not initialized or if metadata length doesn't match documents
        """
        if not documents:
            raise ValueError("Documents list cannot be empty")
        
        # Ensure embedding function is initialized
        await self.embed()
        
        # Prepare metadata
        if metadata is None:
            metadata_list = [{}] * len(documents)
        elif isinstance(metadata, dict):
            # Single metadata dict applies to all documents
            metadata_list = [metadata] * len(documents)
        elif isinstance(metadata, list):
            if len(metadata) != len(documents):
                raise ValueError(f"Metadata list length ({len(metadata)}) must match documents length ({len(documents)})")
            metadata_list = metadata
        else:
            raise ValueError("Metadata must be a dict, list of dicts, or None")
        
        # Convert to LangChain Document objects
        langchain_documents = [
            Document(page_content=doc, metadata=meta)
            for doc, meta in zip(documents, metadata_list)
        ]
        
        # Get vector store and add documents
        vector_store = self._get_vector_store(collection)
        await vector_store.aadd_documents(langchain_documents)

    async def search(self, query: str, top_k: int = 5, collection: str = "default") -> List[Document]:
        """
        Search the vector store for the most similar documents.
        
        Args:
            query: Search query string
            top_k: Number of top results to return
            collection: Collection name to search in
            
        Returns:
            List of Document objects matching the query
            
        Raises:
            ValueError: If embedding function is not initialized or query is empty
        """
        if not query or not query.strip():
            raise ValueError("Query cannot be empty")
        
        if top_k < 1:
            raise ValueError("top_k must be at least 1")
        
        # Ensure embedding function is initialized
        await self.embed()
        
        # Get vector store and perform similarity search
        vector_store = self._get_vector_store(collection)
        results = await vector_store.asimilarity_search(query, k=top_k)
        return results

    async def deleteBySourceUrl(self, source_url: str, collection: str = "default"):
        """
        Delete documents from the vector store by source URL.
        
        Args:
            source_url: Source URL to filter documents for deletion
            collection: Collection name to delete from
            
        Raises:
            ValueError: If source_url is empty or embedding function is not initialized
        """
        if not source_url or not source_url.strip():
            raise ValueError("source_url cannot be empty")
        
        # Ensure embedding function is initialized
        await self.embed()
        
        # Get vector store
        vector_store = self._get_vector_store(collection)
        
        # Access the underlying Chroma collection to use metadata filtering
        # LangChain's Chroma wrapper exposes the collection via _collection property
        try:
            # Try using the vector store's get method with where filter
            results = vector_store.get(where={"source_url": source_url})
            if results and results.get("ids"):
                ids_to_delete = results["ids"]
                if ids_to_delete:
                    await vector_store.adelete(ids=ids_to_delete)
                    return
        except (AttributeError, TypeError):
            # If direct get() doesn't support where filter, access underlying collection
            pass
        
        # Fallback: Access underlying Chroma collection directly
        try:
            chroma_collection = vector_store._collection
            if chroma_collection:
                # Use Chroma's get method with where filter
                query_results = chroma_collection.get(
                    where={"source_url": source_url}
                )
                if query_results and query_results.get("ids"):
                    ids_to_delete = query_results["ids"]
                    if ids_to_delete:
                        await vector_store.adelete(ids=ids_to_delete)
        except Exception as e:
            raise RuntimeError(
                f"Failed to delete documents by source_url '{source_url}': {str(e)}"
            )