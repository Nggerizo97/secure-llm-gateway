from dataclasses import dataclass
from typing import List, Protocol


@dataclass
class RetrievedChunk:
    source_path: str
    content: str


class RetrievalStore(Protocol):
    def index_directory(self, root_dir: str) -> int:
        ...

    def query(self, prompt: str, top_k: int = 2) -> List[RetrievedChunk]:
        ...