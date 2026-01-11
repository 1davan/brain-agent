from sentence_transformers import SentenceTransformer
import numpy as np
from typing import List, Dict, Any
from lru import LRU
import json
from datetime import datetime, timedelta

class VectorProcessor:
    def __init__(self, model_name: str = 'all-mpnet-base-v2', cache_size: int = 1000):
        """
        Initialize vector processor with specified embedding model.
        
        Recommended models:
        - all-mpnet-base-v2: Best quality (768 dims, slower)
        - all-MiniLM-L6-v2: Fast, good quality (384 dims)
        - bge-large-en-v1.5: Excellent for RAG (1024 dims)
        """
        print(f"Loading embedding model: {model_name}")
        try:
            self.embedder = SentenceTransformer(model_name)
            self.model_name = model_name
        except Exception as e:
            print(f"Failed to load {model_name}, falling back to all-MiniLM-L6-v2: {e}")
            self.embedder = SentenceTransformer('all-MiniLM-L6-v2')
            self.model_name = 'all-MiniLM-L6-v2'
        
        self.embedding_cache = LRU(cache_size)  # Cache embeddings
        print(f"Embedding model loaded: {self.model_name}")

    def get_embedding(self, text: str) -> List[float]:
        """Get embedding with caching"""
        if text in self.embedding_cache:
            return self.embedding_cache[text]

        embedding = self.embedder.encode(text).tolist()
        self.embedding_cache[text] = embedding
        return embedding

    def cosine_similarity(self, vec1: List[float], vec2: List[float]) -> float:
        """Calculate cosine similarity - handles dimension mismatch gracefully"""
        if not vec1 or not vec2:
            return 0.0

        v1 = np.array(vec1)
        v2 = np.array(vec2)
        
        # Handle dimension mismatch (old embeddings may have different dimensions)
        if len(v1) != len(v2):
            return 0.0  # Can't compare, will trigger re-embedding

        norm1 = np.linalg.norm(v1)
        norm2 = np.linalg.norm(v2)

        if norm1 == 0 or norm2 == 0:
            return 0.0

        return np.dot(v1, v2) / (norm1 * norm2)

    async def search_similar(self, query: str, items: List[Dict],
                           user_id: str = None, category: str = None,
                           limit: int = 5, threshold: float = 0.3) -> List[Dict]:
        """Search for semantically similar items using embeddings"""
        if not query.strip() or not items:
            return items[:limit] if items else []

        query_embedding = self.get_embedding(query)
        expected_dim = len(query_embedding)

        results = []
        for item in items:
            # Filter by user_id if specified (items may already be filtered)
            if user_id and item.get('user_id') and str(item.get('user_id')) != str(user_id):
                continue
            if category and item.get('category') != category:
                continue

            try:
                # Try to get embedding from item
                item_embedding = item.get('embedding', '[]')
                if isinstance(item_embedding, str):
                    item_embedding = json.loads(item_embedding) if item_embedding else []
                
                # If no stored embedding OR dimension mismatch, regenerate from content
                if not item_embedding or len(item_embedding) != expected_dim:
                    content = item.get('value', item.get('content', item.get('description', '')))
                    if content:
                        item_embedding = self.get_embedding(str(content))
                    else:
                        continue

                similarity = self.cosine_similarity(query_embedding, item_embedding)
                if similarity >= threshold:
                    results.append({
                        **item,
                        'similarity_score': float(similarity)
                    })
            except (json.JSONDecodeError, KeyError, TypeError) as e:
                # If embedding fails, do a simple text match as fallback
                content = str(item.get('value', item.get('content', ''))).lower()
                if query.lower() in content:
                    results.append({
                        **item,
                        'similarity_score': 0.5  # Medium score for text match
                    })

        # Sort by similarity and return top results
        results.sort(key=lambda x: x.get('similarity_score', 0), reverse=True)
        return results[:limit]

    async def generate_memory_embedding(self, category: str, key: str, value: str) -> str:
        """Generate embedding for memory storage"""
        # Combine category, key, and value for better semantic understanding
        combined_text = f"{category}: {key} - {value}"
        embedding = self.get_embedding(combined_text)
        return json.dumps(embedding)

    def clear_cache(self):
        """Clear embedding cache"""
        self.embedding_cache.clear()