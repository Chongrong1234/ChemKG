"""检索回归评测脚本.

在带 gold_evidence_ids 标注的评测集上计算 recall@k / hit@k / sufficient@k，
用于检索层改动前后的回归对比（silver 集，仅作回归护栏，不当作 gold 结论）。

用法::

    python scripts/eval_retrieval.py --gold ../evaluation/auto_silver.jsonl \
        --strategy kg --k 5 --out /tmp/eval_kg.json
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from kgrag.index.store import IndexStore  # noqa: E402
from kgrag.retrieval.pipeline import RetrievalPipeline  # noqa: E402
from kgrag.schemas import RetrievalRequest  # noqa: E402
from kgrag.config import get_settings  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--index", default=str(get_settings().index_dir))
    ap.add_argument("--gold", required=True)
    ap.add_argument("--strategy", default="kg")
    ap.add_argument("--k", type=int, default=5)
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    store = IndexStore.load(args.index)
    pipe = RetrievalPipeline(store)
    items = [json.loads(x) for x in Path(args.gold).read_text(encoding="utf-8").splitlines() if x.strip()]

    per = []
    for g in items:
        req = RetrievalRequest(question=g["question"], strategy=args.strategy, topk=args.k)
        ids = {h.row.evidence_id for h in pipe.retrieve(req)}
        gold = set(g.get("gold_evidence_ids", []))
        per.append({
            "id": g.get("id"),
            "hit": bool(ids & gold) if gold else None,
            "recall": len(ids & gold) / len(gold) if gold else None,
            "sufficient": bool(gold and gold <= ids),
        })

    def avg(key: str) -> float | None:
        xs = [r[key] for r in per if r[key] is not None]
        return sum(xs) / len(xs) if xs else None

    report = {
        "gold": args.gold, "strategy": args.strategy, "k": args.k, "n": len(per),
        "hit_at_k": avg("hit"),
        "evidence_recall_at_k": avg("recall"),
        "sufficient_evidence_rate": avg("sufficient"),
    }
    text = json.dumps(report, ensure_ascii=False, indent=2)
    print(text)
    if args.out:
        Path(args.out).write_text(text, encoding="utf-8")


if __name__ == "__main__":
    main()
