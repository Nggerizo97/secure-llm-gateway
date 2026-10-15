import hashlib
from pathlib import Path
from typing import List
from app.retrieval.interface import RetrievedChunk

ALLOWED_EXTENSIONS = {".py", ".md", ".txt"}
EXCLUDED_DIRS = {".git", "__pycache__", ".venv", "venv", "data", "secrets", "models"}
EXCLUDED_FILENAMES = {".env", ".env.example"}
EXCLUDED_SUFFIXES = {".pem", ".key", ".sqlite", ".db", ".log"}
MAX_FILE_BYTES = 64 * 1024  # 64 KB cap per file


def is_safe_sample_file(path: Path) -> bool:
    """Enforce Section 8 RAG indexing rules on candidate files."""
    if not path.is_file():
        return False
    if any(part in EXCLUDED_DIRS for part in path.parts):
        return False
    if path.name in EXCLUDED_FILENAMES or path.name.startswith(".env"):
        return False
    if path.suffix.lower() in EXCLUDED_SUFFIXES:
        return False
    if path.suffix.lower() not in ALLOWED_EXTENSIONS:
        return False
    if path.stat().st_size > MAX_FILE_BYTES:
        return False
    return True


class LocalHashEmbeddingFunction:
    """Zero-network deterministic embedding function for local/offline ChromaDB demos."""

    def __call__(self, input: List[str]) -> List[List[float]]:
        embeddings: List[List[float]] = []
        for text in input:
            vec = [0.0] * 32
            for token in text.lower().split():
                digest = hashlib.sha256(token.encode("utf-8")).digest()
                for i in range(32):
                    vec[i] += (digest[i] / 255.0) - 0.5
            norm = sum(x * x for x in vec) ** 0.5 or 1.0
            embeddings.append([x / norm for x in vec])
        return embeddings

    def embed_query(self, input: List[str]) -> List[List[float]]:
        return self(input)

    def name(self) -> str:
        return "local_hash_embedding_v1"


class ChromaRetrievalStore:
    def __init__(self, persist_dir: str = "./data/chroma", collection_name: str = "synthetic_sample_code"):
        # Lazy import so core mock mode never requires chromadb installed
        import chromadb

        Path(persist_dir).mkdir(parents=True, exist_ok=True)
        self._client = chromadb.PersistentClient(path=persist_dir)
        self._embedding_fn = LocalHashEmbeddingFunction()
        self._collection = self._client.get_or_create_collection(
            name=collection_name,
            embedding_function=self._embedding_fn,  # type: ignore[arg-type]
        )

    def index_directory(self, root_dir: str = "./sample_project") -> int:
        root = Path(root_dir)
        if not root.exists():
            return 0

        ids: List[str] = []
        documents: List[str] = []
        metadatas: List[dict] = []

        for file_path in sorted(root.rglob("*")):
            if not is_safe_sample_file(file_path):
                continue
            text = file_path.read_text(encoding="utf-8", errors="ignore").strip()
            if not text:
                continue

            rel_path = file_path.relative_to(root).as_posix()
            # Split into simple paragraph/function chunks (~500 chars)
            chunks = [text[i : i + 500] for i in range(0, len(text), 500)]
            for idx, chunk in enumerate(chunks):
                doc_id = f"{rel_path}::chunk_{idx}"
                ids.append(doc_id)
                documents.append(chunk)
                metadatas.append({"source": rel_path})

        if ids:
            self._collection.upsert(ids=ids, documents=documents, metadatas=metadatas)
        return len(ids)

    def query(self, prompt: str, top_k: int = 2) -> List[RetrievedChunk]:
        if self._collection.count() == 0:
            return []
        n_results = min(top_k, self._collection.count())
        result = self._collection.query(query_texts=[prompt], n_results=n_results)
        docs = (result.get("documents") or [[]])[0]
        metas = (result.get("metadatas") or [[]])[0]

        retrieved: List[RetrievedChunk] = []
        for doc, meta in zip(docs, metas):
            source = str((meta or {}).get("source", "unknown"))
            retrieved.append(RetrievedChunk(source_path=source, content=str(doc)))
        return retrieved