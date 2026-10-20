#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Dense reranker: BM25 candidate generation (broad recall) + BGE cross-encoder-style
reranking by query-document cosine similarity.

This keeps BM25's precision on template questions while letting embeddings reorder
candidates. Usage mirrors rag_hybrid.py.
"""
from __future__ import annotations
import argparse, json, os, statistics, time
from pathlib import Path
from rag_system import load_index, retrieve

MODEL_NAME = os.environ.get("RAG_EMBED_MODEL", "BAAI/bge-small-zh-v1.5")
QUERY_PREFIX = os.environ.get("RAG_QUERY_PREFIX", "为这个句子生成表示以用于检索相关文章：")

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--index", default="rag_index")
    ap.add_argument("--gold", required=True)
    ap.add_argument("--k", type=int, default=5)
    ap.add_argument("--candidates", type=int, default=50)
    ap.add_argument("--batch", type=int, default=256)
    ap.add_argument("--out", default="evaluation/rerank.json")
    ap.add_argument("--no-kg-boost", action="store_true")
    a = ap.parse_args()

    from sentence_transformers import SentenceTransformer
    import numpy as np

    idx = load_index(Path(a.index))
    rows = idx["rows"]
    model = SentenceTransformer(MODEL_NAME)

    items = [json.loads(x) for x in Path(a.gold).read_text(encoding="utf-8").splitlines() if x.strip()]

    per = []
    for g in items:
        t = time.perf_counter()
        cand = retrieve(idx, g["question"], a.candidates, 1, kg_boost=not a.no_kg_boost)
        if not cand:
            per.append({"id": g.get("id"), "hit": None, "recall": None, "sufficient": False,
                        "retrieved": [], "latency_ms": (time.perf_counter() - t) * 1000})
            continue
        cand_texts = [c["text"] for c in cand]
        q = model.encode([QUERY_PREFIX + g["question"]], normalize_embeddings=True, show_progress_bar=False)
        d = model.encode(cand_texts, batch_size=a.batch, normalize_embeddings=True, show_progress_bar=False)
        sims = (d @ q[0]).ravel()
        order = np.argsort(-sims)[: a.k]
        hits = [{**cand[i], "score": round(float(sims[i]), 6), "bm25_rank": i} for i in order]
        ms = (time.perf_counter() - t) * 1000

        ids = {h["evidence_id"] for h in hits}
        gold = set(g.get("gold_evidence_ids", []))
        per.append({
            "id": g.get("id"),
            "hit": bool(ids & gold) if gold else None,
            "recall": len(ids & gold) / len(gold) if gold else None,
            "sufficient": bool(gold and gold <= ids),
            "retrieved": [h["evidence_id"] for h in hits],
            "latency_ms": ms,
        })

    def avg(key):
        xs = [r[key] for r in per if r[key] is not None]
        return sum(xs) / len(xs) if xs else None

    report = {
        "model": MODEL_NAME,
        "strategy": "bm25_candidates+dense_rerank",
        "candidates": a.candidates,
        "kg_boost": not a.no_kg_boost,
        "k": a.k,
        "n": len(per),
        "hit_at_k": avg("hit"),
        "evidence_recall_at_k": avg("recall"),
        "sufficient_evidence_rate": avg("sufficient"),
        "latency_ms_p50": statistics.median([r["latency_ms"] for r in per]),
        "latency_ms_mean": statistics.mean([r["latency_ms"] for r in per]),
        "warning": "silver labels; per-query embedding, slower than precomputed variants",
    }
    Path(a.out).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))

if __name__ == "__main__":
    main()
