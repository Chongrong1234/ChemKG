#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Dense retrieval baseline with a real neural embedding (BAAI/bge-small-zh-v1.5).

Encodes the same evidence rows used by the BM25 index and evaluates Hit@k /
Recall@k on the silver sets. Run with:
  HF_ENDPOINT=https://hf-mirror.com LD_PRELOAD=/opt/conda/lib/libstdc++.so.6 \
  python rag_dense_bge.py --index rag_index --gold evaluation/auto_entity_silver.jsonl --k 5
"""
from __future__ import annotations
import argparse, json, os, statistics, time
from pathlib import Path
from rag_system import load_index

MODEL_NAME = os.environ.get("RAG_EMBED_MODEL", "BAAI/bge-small-zh-v1.5")

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--index", default="rag_index")
    ap.add_argument("--gold", required=True)
    ap.add_argument("--k", type=int, default=5)
    ap.add_argument("--batch", type=int, default=256)
    ap.add_argument("--out", default="evaluation/dense_bge.json")
    ap.add_argument("--query-prefix", default="为这个句子生成表示以用于检索相关文章：")
    a = ap.parse_args()

    from sentence_transformers import SentenceTransformer
    import numpy as np

    idx = load_index(Path(a.index))
    rows = idx["rows"]
    texts = [r["text"] for r in rows]
    model = SentenceTransformer(MODEL_NAME)

    t0 = time.perf_counter()
    doc_emb = model.encode(texts, batch_size=a.batch, normalize_embeddings=True, show_progress_bar=False)
    enc_ms = (time.perf_counter() - t0) * 1000

    items = [json.loads(x) for x in Path(a.gold).read_text(encoding="utf-8").splitlines() if x.strip()]
    queries = [g["question"] for g in items]
    # bge-small-zh uses a query instruction for retrieval tasks.
    q_emb = model.encode([a.query_prefix + q for q in queries], batch_size=a.batch,
                         normalize_embeddings=True, show_progress_bar=False)

    per = []
    for qi, g in enumerate(items):
        t = time.perf_counter()
        sims = doc_emb @ q_emb[qi]
        top = np.argsort(-sims)[: a.k]
        ms = (time.perf_counter() - t) * 1000
        ids = {rows[i]["evidence_id"] for i in top}
        gold = set(g.get("gold_evidence_ids", []))
        per.append({
            "id": g.get("id"),
            "hit": bool(ids & gold) if gold else None,
            "recall": len(ids & gold) / len(gold) if gold else None,
            "sufficient": bool(gold and gold <= ids),
            "latency_ms": ms,
        })

    def avg(key):
        xs = [r[key] for r in per if r[key] is not None]
        return sum(xs) / len(xs) if xs else None

    report = {
        "model": MODEL_NAME,
        "corpus_n": len(rows),
        "encode_ms_total": round(enc_ms, 1),
        "k": a.k,
        "hit_at_k": avg("hit"),
        "evidence_recall_at_k": avg("recall"),
        "sufficient_evidence_rate": avg("sufficient"),
        "latency_ms_p50": statistics.median([r["latency_ms"] for r in per]),
        "latency_ms_mean": statistics.mean([r["latency_ms"] for r in per]),
        "warning": "silver labels; dense baseline only, no KG features",
    }
    Path(a.out).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))

if __name__ == "__main__":
    main()
