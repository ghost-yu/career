import json
import os
import math
from typing import List, Dict, Any

# 持久化存储路径
STORE_FILE = os.path.join(os.path.dirname(__file__), '../../data/chunk_store.json')

def cosine_similarity(v1: List[float], v2: List[float]) -> float:
    dot_product = sum(a * b for a, b in zip(v1, v2))
    norm_v1 = math.sqrt(sum(a * a for a in v1))
    norm_v2 = math.sqrt(sum(b * b for b in v2))
    if norm_v1 == 0 or norm_v2 == 0:
        return 0.0
    return dot_product / (norm_v1 * norm_v2)

class SimpleDocumentStore:
    def __init__(self, store_path: str = STORE_FILE):
        self.store_path = store_path
        self.documents: List[Dict[str, Any]] = []
        self._load()

    def _load(self):
        if os.path.exists(self.store_path):
            try:
                with open(self.store_path, 'r', encoding='utf-8') as f:
                    self.documents = json.load(f)
            except Exception as e:
                print(f"无法加载向量库: {e}")

    def save(self):
        os.makedirs(os.path.dirname(self.store_path), exist_ok=True)
        tmp_path = self.store_path + ".tmp"
        # 先写临时文件，防中断导致 JSON 损坏
        with open(tmp_path, 'w', encoding='utf-8') as f:
            json.dump(self.documents, f, ensure_ascii=False, indent=2)
        # 写完再原子替换
        os.replace(tmp_path, self.store_path)

    def add_document(self, text: str, embedding: List[float], metadata: Dict[str, Any] = None):
        doc = {
            "text": text,
            "embedding": embedding,
            "metadata": metadata or {}
        }
        self.documents.append(doc)

    def search(self, query_embedding: List[float], top_k: int = 3) -> List[Dict[str, Any]]:
        if not self.documents or not query_embedding:
            return []
            
        scored_docs = []
        for doc in self.documents:
            score = cosine_similarity(query_embedding, doc['embedding'])
            scored_docs.append((score, doc))
            
        # 按相似度降序排序
        scored_docs.sort(key=lambda x: x[0], reverse=True)
        
        # 返回 top_k
        results = []
        for score, doc in scored_docs[:top_k]:
            results.append({
                "score": score,
                "text": doc["text"],
                "metadata": doc["metadata"]
            })
        return results

_doc_store: SimpleDocumentStore | None = None


def get_doc_store() -> SimpleDocumentStore:
    global _doc_store
    if _doc_store is None:
        _doc_store = SimpleDocumentStore()
    return _doc_store
