"""KG 图扩展（保守策略）.

当前 KG 事实表是“携带谓词的证据记录”，尚未完全归一化为
subject-predicate-object 三元组，因此本模块只沿两个明确信号扩展：
1. 问题中的关系词命中谓词 -> 拉入同谓词的其它证据；
2. 命中证据的实体 -> 拉入共享实体的其它证据。

不推断未经 KG 明确支持的图路径（沿用原系统的安全边界）。
"""

from __future__ import annotations

from collections import defaultdict


def build_graph(rows) -> dict:
    by_doc: defaultdict[str, list] = defaultdict(list)
    by_pred: defaultdict[str, list] = defaultdict(list)
    by_entity: defaultdict[str, list] = defaultdict(list)
    for r in rows:
        by_doc[r.doc_id].append(r)
        for p in r.predicates:
            by_pred[p].append(r)
        for e in r.entities:
            by_entity[e.lower()].append(r)
    return {"by_doc": by_doc, "by_pred": by_pred, "by_entity": by_entity}


def expand(store, hits, question: str, limit: int = 20) -> list:
    """基于谓词与共享实体扩展候选证据（返回含 graph_expansion 标记的列表）."""
    graph = build_graph(store.rows)
    out = list(hits)
    seen = {h.row.evidence_id for h in out}
    q = question.lower()

    # 1) 谓词信号
    for pred, rows in graph["by_pred"].items():
        if pred.replace("_", " ") in q or any(a in q for a in pred.split("_")):
            for row in rows:
                if row.evidence_id not in seen:
                    out.append(_as_expansion(row, seen))
                if len(out) >= limit:
                    return out
    # 2) 共享实体信号
    for hit in hits:
        for ent in hit.row.entities:
            for row in graph["by_entity"].get(ent.lower(), []):
                if row.evidence_id not in seen:
                    out.append(_as_expansion(row, seen))
                if len(out) >= limit:
                    return out
    return out


def _as_expansion(row, seen: set):
    from kgrag.schemas import RetrievalHit

    seen.add(row.evidence_id)
    return RetrievalHit(
        row=row,
        score=0.0,
        matched_terms=[],
        graph_expansion=True,
    )
