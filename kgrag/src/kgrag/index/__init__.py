"""索引子包：BM25 倒排索引的构建与加载."""

from kgrag.index.builder import build_index
from kgrag.index.store import IndexStore

__all__ = ["IndexStore", "build_index"]
