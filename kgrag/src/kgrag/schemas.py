"""领域数据模型.

统一使用 ``dataclass``（纯检索层）与 ``pydantic``（API 边界校验），
保证内部模块不依赖 Web 框架。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class EvidenceRow:
    """一条可检索的文献证据（来自 kg_data/evidence.csv 及其关联表）.

    网络检索证据（联网搜索）复用同一结构：``source="web"``，
    ``journal/year/authors/doi`` 仅网络证据填充。
    """

    evidence_id: str
    doc_id: str
    line_no: int
    text: str
    title: str = ""
    path: str = ""
    entities: list[str] = field(default_factory=list)
    values: list[str] = field(default_factory=list)
    predicates: list[str] = field(default_factory=list)
    tokens: list[str] = field(default_factory=list)
    dl: int = 0
    # ---- 网络证据扩展字段 ----
    source: str = "local"           # "local" | "web"
    journal: str = ""               # 期刊名（web）
    year: int | None = None         # 发表年份（web）
    authors: list[str] = field(default_factory=list)  # 作者（web）
    doi: str = ""                   # DOI（web）


@dataclass
class NeighborLine:
    """同文档相邻证据行（上下文窗口）."""

    evidence_id: str
    line_no: int
    text: str


@dataclass
class RetrievalHit:
    """一次检索命中的完整结果."""

    row: EvidenceRow
    score: float
    matched_terms: list[str]
    neighbors: list[NeighborLine] = field(default_factory=list)
    graph_expansion: bool = False

    def to_dict(self) -> dict[str, Any]:
        """序列化为 JSON 友好的 dict（供 API/前端使用）."""
        d = {
            "evidence_id": self.row.evidence_id,
            "doc_id": self.row.doc_id,
            "title": self.row.title,
            "path": self.row.path,
            "line_no": self.row.line_no,
            "text": self.row.text,
            "entities": self.row.entities,
            "values": self.row.values,
            "predicates": self.row.predicates,
            "score": round(self.score, 6),
            "matched_terms": self.matched_terms,
            "graph_expansion": self.graph_expansion,
            "neighbors": [
                {"evidence_id": n.evidence_id, "line_no": n.line_no, "text": n.text}
                for n in self.neighbors
            ],
        }
        if self.row.source == "web":
            d.update({
                "source": "web",
                "journal": self.row.journal,
                "year": self.row.year,
                "authors": self.row.authors,
                "doi": self.row.doi,
            })
        return d


# ---------------------------------------------------------------------------
# 检索策略（前端可选，后端校验）
# ---------------------------------------------------------------------------

RETRIEVAL_STRATEGIES: dict[str, str] = {
    "lexical": "纯词法 BM25 检索（不含 KG 加权）",
    "kg": "BM25 + 知识图谱增强（实体/关系/数值加权，默认推荐）",
    "anchored": "BM25 + KG + 主体锚定（对指明材料的提问重排序）",
    "graph": "BM25 + KG + 图扩展（沿谓词/实体扩展相邻证据）",
}
DEFAULT_STRATEGY = "kg"


@dataclass
class RetrievalRequest:
    """检索层统一入参."""

    question: str
    strategy: str = DEFAULT_STRATEGY
    topk: int = 8
    window: int = 1
    doc_id: str | None = None
    subject: str | None = None
    predicate_hint: str | None = None
