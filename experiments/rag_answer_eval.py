#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Answer-level gold evaluation harness.

For each item in evaluation/gold_qa.jsonl:
1. Retrieve top-k evidence (subject-anchored v3 retrieval).
2. Generate answers with several systems:
   - extractive: deterministic evidence excerpts (no LLM);
   - LLM (per configured model): grounded answer from retrieved evidence.
3. Save per-item results for LLM-as-judge scoring (rag_judge.py).

Usage:
  python rag_answer_eval.py --index rag_index_strict --gold evaluation/gold_qa.jsonl \
      --models glm-5.3 qwen3.7-max deepseek-v4-pro-0813 kimi-k2.6 --out evaluation/answers.jsonl
"""
from __future__ import annotations
import argparse, json, os, time, urllib.request, urllib.error
from pathlib import Path
import sys
sys.path.insert(0, ".")
from rag_system import load_index, retrieve, extractive_answer

API_BASE = os.environ.get("RAG_LLM_BASE_URL", "https://api.epicllmrouter.top/v1")
API_KEY = os.environ.get("RAG_LLM_API_KEY", "")

SYS_PROMPT = (
    "你是电镀科研文献问答助手。规则：1) 只依据给定证据回答，不能由证据推出的内容明确说证据不足；"
    "2) 保留实验条件（浓度、温度、电流密度、pH、电位、转速等）；"
    "3) 明确回答问题中的关系（抑制/加速/协同/改善填充），若证据不支持该关系要直说；"
    "4) 引用证据编号 [E1] [E2]；5) 不编造数值。回答控制在 150 字内。"
)

def llm_answer(question, evidence, model, base=None, key=None):
    base = base or API_BASE; key = key or API_KEY
    if not key:
        return None
    ctx = "\n".join(f"[E{i}] {h['text']}" for i, h in enumerate(evidence, 1))
    body = json.dumps({
        "model": model, "temperature": 0, "max_tokens": 600,
        "messages": [
            {"role": "system", "content": SYS_PROMPT},
            {"role": "user", "content": f"问题：{question}\n\n证据：\n{ctx}"},
        ],
    }, ensure_ascii=False).encode()
    req = urllib.request.Request(
        base.rstrip("/") + "/chat/completions", data=body,
        headers={"Content-Type": "application/json", "Authorization": "Bearer " + key})
    last_err = None
    for _ in range(3):
        try:
            with urllib.request.urlopen(req, timeout=120) as resp:
                data = json.loads(resp.read())
            content = data["choices"][0]["message"].get("content") or ""
            if not content.strip():
                # reasoning models sometimes put everything in reasoning_content
                content = data["choices"][0]["message"].get("reasoning_content") or ""
            return content
        except Exception as e:
            last_err = e
            time.sleep(2)
    return f"[LLM error: {type(last_err).__name__}]"

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--index", default="rag_index_strict")
    ap.add_argument("--gold", default="evaluation/gold_qa.jsonl")
    ap.add_argument("--models", nargs="*", default=["glm-5.3"])
    ap.add_argument("--k", type=int, default=5)
    ap.add_argument("--out", default="evaluation/answers.jsonl")
    ap.add_argument("--panel-mode", default="intent", choices=["off", "trust", "refute", "intent"],
                    help="jury 状态软加权：intent=按条目意图路由（answerable→trust, 对抗→refute）")
    ap.add_argument("--retrieval", default="final", choices=["final", "lexical"],
                    help="final=完整系统（KG加权+锚定+意图路由）；lexical=朴素词法BM25（对比实验基线）")
    a = ap.parse_args()

    idx = load_index(Path(a.index))
    gold = [json.loads(x) for x in Path(a.gold).read_text(encoding="utf-8").splitlines() if x.strip()]

    out = []
    for g in gold:
        if a.retrieval == "lexical":
            hits = retrieve(idx, g["question"], a.k, 1, kg_boost=False)
        else:
            pm = a.panel_mode
            if pm == "intent":
                pm = "trust" if g.get("answerable") else "refute"
            hits = retrieve(idx, g["question"], a.k, 1, kg_boost=True,
                            subject_anchor=g["subject"], predicate_hint=g["predicate"],
                            panel_mode=pm)
        rec = {
            "id": g["id"], "question": g["question"], "answerable": g["answerable"],
            "gold_answer": g["gold_answer"], "label": g["label"],
            "predicate": g["predicate"], "subject": g["subject"],
            "gold_evidence_ids": g["gold_evidence_ids"],
            "retrieved_evidence": [
                {"evidence_id": h["evidence_id"], "score": h["score"], "text": h["text"][:400]}
                for h in hits],
        }
        rec["answers"] = {"extractive": extractive_answer(g["question"], hits)}
        for m in a.models:
            t0 = time.perf_counter()
            ans = llm_answer(g["question"], hits, m)
            rec["answers"][m] = ans
            rec.setdefault("latency_ms", {})[m] = round((time.perf_counter() - t0) * 1000)
        out.append(rec)
        print(f"done {g['id']} ({len(hits)} evidence)", flush=True)

    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    with open(a.out, "w", encoding="utf-8") as f:
        for r in out:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(json.dumps({"out": a.out, "items": len(out), "models": a.models}, ensure_ascii=False))

if __name__ == "__main__":
    main()
