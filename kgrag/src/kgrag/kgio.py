"""KG CSV 数据读取层.

kg_data 目录下的六张表构成文献知识图谱::

    documents.csv  文档元数据（doc_id, path, title, sha1, char_count）
    evidence.csv   证据行（evidence_id, doc_id, line_no, text, review_status）
    facts.csv      候选事实（fact_id, evidence_id, predicate, surface_text, ...）
    entities.csv   实体表（entity_id, name, entity_type, ...）
    mentions.csv   实体提及（mention_id, entity_id, evidence_id, text, ...）
    values.csv     数值参数（value_id, evidence_id, value, unit, ...）

候选事实（CandidateFact）不自动等同于科学结论——
该边界沿用原系统设计，在本层不做任何“事实升级”。
"""

from __future__ import annotations

import csv
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

KG_TABLES = ("documents", "evidence", "facts", "entities", "mentions", "values")


def _read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open(encoding="utf-8", newline="") as fh:
        return [dict(r) for r in csv.DictReader(fh)]


@dataclass
class KGCorpus:
    """从 CSV 载入的完整 KG 语料（构建索引的中间表示）."""

    documents: list[dict[str, str]] = field(default_factory=list)
    evidence: list[dict[str, str]] = field(default_factory=list)
    facts: list[dict[str, str]] = field(default_factory=list)
    entities: list[dict[str, str]] = field(default_factory=list)
    mentions: list[dict[str, str]] = field(default_factory=list)
    values: list[dict[str, str]] = field(default_factory=list)

    @classmethod
    def load(cls, kg_dir: str | Path) -> "KGCorpus":
        kg_dir = Path(kg_dir)
        corpus = cls()
        for name in KG_TABLES:
            rows = _read_csv(kg_dir / f"{name}.csv")
            setattr(corpus, name, rows)
        if not corpus.evidence:
            raise FileNotFoundError(f"未在 {kg_dir} 找到 evidence.csv，请确认 KG 数据目录")
        return corpus

    def evidence_enrichment(self) -> dict[str, dict[str, list[str]]]:
        """按 evidence_id 聚合实体/数值/谓词富化信息."""
        name_by_id = {r.get("entity_id", ""): r.get("name", "") for r in self.entities}
        by_ev: dict[str, dict[str, list[str]]] = defaultdict(
            lambda: {"entities": [], "values": [], "predicates": []}
        )
        for m in self.mentions:
            eid = m.get("evidence_id", "")
            label = m.get("text") or name_by_id.get(m.get("entity_id", ""), "")
            if label:
                by_ev[eid]["entities"].append(label)
        for v in self.values:
            ev = by_ev[v.get("evidence_id", "")]
            ev["values"].append(f"{v.get('value', '')} {v.get('unit', '')}".strip())
        for f in self.facts:
            by_ev[f.get("evidence_id", "")]["predicates"].append(f.get("predicate", ""))
        return dict(by_ev)

    def stats(self) -> dict[str, int]:
        return {
            "documents": len(self.documents),
            "evidence": len(self.evidence),
            "facts": len(self.facts),
            "entities": len(self.entities),
            "mentions": len(self.mentions),
            "values": len(self.values),
        }
