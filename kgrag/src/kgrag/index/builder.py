"""索引构建器.

从 kg_data CSV 构建 BM25 倒排索引并持久化为 ``index.json``。
索引格式与既有 v2 版本保持兼容（rows/df/inv/doc_rows...），
旧索引可直接被 :class:`kgrag.index.store.IndexStore` 加载。
"""

from __future__ import annotations

import hashlib
import json
from collections import Counter, defaultdict
from pathlib import Path

from kgrag.kgio import KGCorpus
from kgrag.schemas import EvidenceRow
from kgrag.textproc import tokenize

INDEX_VERSION = 2


def _sha16(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8", "ignore")).hexdigest()[:16]


def build_index(kg_dir: str | Path, out_dir: str | Path, *, strict_predicates: set[str] | None = None) -> dict:
    """构建 BM25 倒排索引.

    :param kg_dir: KG CSV 数据目录
    :param out_dir: 索引输出目录（写入 index.json）
    :param strict_predicates: 若给定，仅保留含这些谓词的证据行（严格模式）
    :return: 索引统计信息 dict
    """
    kg_dir, out_dir = Path(kg_dir), Path(out_dir)
    corpus = KGCorpus.load(kg_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    docs = {r["doc_id"]: r for r in corpus.documents}
    enrichment = corpus.evidence_enrichment()

    rows: list[EvidenceRow] = []
    for e in corpus.evidence:
        eid = e.get("evidence_id", "")
        en = enrichment.get(eid, {"entities": [], "values": [], "predicates": []})
        if strict_predicates is not None and not (set(en["predicates"]) & strict_predicates):
            continue
        doc = docs.get(e.get("doc_id", ""), {})
        text = e.get("text", "")
        enriched = " ".join([text] + en["entities"] + en["values"] + en["predicates"])
        toks = tokenize(enriched)
        rows.append(
            EvidenceRow(
                evidence_id=eid,
                doc_id=e.get("doc_id", ""),
                line_no=int(e.get("line_no") or 0),
                text=text,
                title=doc.get("title", ""),
                path=doc.get("path", ""),
                entities=en["entities"],
                values=en["values"],
                predicates=en["predicates"],
                tokens=toks,
                dl=len(toks),
            )
        )

    # 文档频率 + 倒排链
    df: Counter[str] = Counter()
    inv: defaultdict[str, list[int]] = defaultdict(list)
    for i, row in enumerate(rows):
        for t in set(row.tokens):
            df[t] += 1
            inv[t].append(i)

    doc_rows: defaultdict[str, list[int]] = defaultdict(list)
    for i, row in enumerate(rows):
        doc_rows[row.doc_id].append(i)

    source_files = {}
    for name in ("documents.csv", "evidence.csv", "facts.csv", "entities.csv", "mentions.csv", "values.csv"):
        p = kg_dir / name
        if p.exists():
            source_files[name] = {"bytes": p.stat().st_size, "sha1": hashlib.sha1(p.read_bytes()).hexdigest()}

    payload = {
        "version": INDEX_VERSION,
        "source_kg": str(kg_dir.resolve()),
        "source_files": source_files,
        "rows": [r.__dict__ for r in rows],
        "df": dict(df),
        "inv": dict(inv),
        "N": len(rows),
        "avgdl": (sum(r.dl for r in rows) / len(rows)) if rows else 0.0,
        "doc_rows": dict(doc_rows),
    }
    (out_dir / "index.json").write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    return {
        "evidence": len(rows),
        "documents": len(docs),
        "facts": len(corpus.facts),
        "entities": len(corpus.entities),
        "out": str(out_dir),
    }
