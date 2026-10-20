"""索引加载与运行时存储.

:class:`IndexStore` 持有全部索引数据（行、倒排链、文档频率、同文档行号映射），
是检索层的唯一数据源。兼容加载既有 v2 版 ``index.json``。
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

from kgrag.schemas import EvidenceRow


class IndexStore:
    """BM25 倒排索引的内存只读视图."""

    def __init__(self, payload: dict):
        self.version: int = int(payload.get("version", 2))
        self.source_kg: str = payload.get("source_kg", "")
        self.source_files: dict = payload.get("source_files", {})
        self.rows: list[EvidenceRow] = [self._parse_row(r) for r in payload.get("rows", [])]
        self.df: dict[str, int] = payload.get("df", {})
        self.inv: dict[str, list[int]] = payload.get("inv", {})
        self.n: int = int(payload.get("N", len(self.rows)))
        self.avgdl: float = float(payload.get("avgdl", 1.0) or 1.0)
        self.doc_rows: dict[str, list[int]] = payload.get("doc_rows", {})

    @staticmethod
    def _parse_row(r: dict) -> EvidenceRow:
        return EvidenceRow(
            evidence_id=r.get("evidence_id", ""),
            doc_id=r.get("doc_id", ""),
            line_no=int(r.get("line_no") or 0),
            text=r.get("text", ""),
            title=r.get("title", ""),
            path=r.get("path", ""),
            entities=list(r.get("entities") or []),
            values=list(r.get("values") or []),
            predicates=list(r.get("predicates") or []),
            tokens=list(r.get("tokens") or []),
            dl=int(r.get("dl", 0) or 0),
        )

    @classmethod
    def load(cls, index_dir: str | Path) -> "IndexStore":
        index_dir = Path(index_dir)
        path = index_dir / "index.json"
        if not path.exists():
            raise FileNotFoundError(f"索引文件不存在：{path}（先运行 scripts/build_index.py）")
        payload = json.loads(path.read_text(encoding="utf-8"))
        return cls(payload)

    # ------------------------------------------------------------------
    # 供检索层使用的访问接口
    # ------------------------------------------------------------------
    def postings(self, term: str) -> list[int]:
        """返回包含某词元的行下标列表（倒排链）."""
        return self.inv.get(term, [])

    def doc_freq(self, term: str) -> int:
        return self.df.get(term, 0)

    def rows_of_doc(self, doc_id: str) -> list[int]:
        return self.doc_rows.get(doc_id, [])

    def row_by_id(self, evidence_id: str) -> EvidenceRow | None:
        for row in self.rows:
            if row.evidence_id == evidence_id:
                return row
        return None

    def stats(self) -> dict:
        return {
            "index_version": self.version,
            "evidence_count": self.n,
            "document_count": len(self.doc_rows),
            "vocabulary_size": len(self.df),
            "source_kg": self.source_kg,
        }
