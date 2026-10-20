#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""LLM-as-judge scoring for answer-level gold evaluation.

Each judge model scores each (system answer, gold) pair on:
- correctness (0-2): 2=correct relation+direction, 1=partially correct, 0=wrong
- evidence_support (0-2): answer cites evidence that actually supports it
- condition_retention (0-2): experimental conditions preserved
- abstention (0/1): correctly declines when unsupported (adversarial items)

Usage:
  RAG_LLM_API_KEY=... python rag_judge.py --answers evaluation/answers.jsonl \
      --judges glm-5.3 qwen3.7-max deepseek-v4-pro-0813 kimi-k2.6 --out evaluation/judged.jsonl
"""
from __future__ import annotations
import argparse, json, os, time, urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

API_BASE = os.environ.get("RAG_LLM_BASE_URL", "https://api.epicllmrouter.top/v1")
API_KEY = os.environ.get("RAG_LLM_API_KEY", "")

JUDGE_SYS = (
    "你是严格的科研问答评测裁判。根据参考答案与证据，对候选回答打分，只输出 JSON：\n"
    '{"correctness": 0|1|2, "evidence_support": 0|1|2, "condition_retention": 0|1|2, "abstention": 0|1, "reason": "一句话"}\n'
    "评分标准：correctness 2=关系方向与内容正确且完整；1=部分正确或含糊；0=错误。\n"
    "evidence_support 2=引用的证据确实支持该结论；1=引用了证据但支持不充分；0=未引用或引用错误。\n"
    "condition_retention 2=保留了关键实验条件；1=保留了部分；0=丢失条件或编造条件。\n"
    "abstention：若参考答案说明该说法不被支持，回答正确拒绝则 1，否则 0。"
)

def call_judge(question, gold_answer, candidate, evidence_texts, judge_model):
    ctx = "\n".join(f"[E{i}] {t[:300]}" for i, t in enumerate(evidence_texts, 1))
    body = json.dumps({
        "model": judge_model, "temperature": 0, "max_tokens": 2500,
        "messages": [
            {"role": "system", "content": JUDGE_SYS},
            {"role": "user", "content":
                f"问题：{question}\n\n参考答案（gold）：{gold_answer}\n\n"
                f"候选回答：{candidate}\n\n证据：\n{ctx}"},
        ],
    }, ensure_ascii=False).encode()
    req = urllib.request.Request(
        API_BASE.rstrip("/") + "/chat/completions", data=body,
        headers={"Content-Type": "application/json", "Authorization": "Bearer " + API_KEY})
    for _ in range(3):
        try:
            with urllib.request.urlopen(req, timeout=180) as resp:
                data = json.loads(resp.read())
            msg = data["choices"][0]["message"]
            content = (msg.get("content") or "").strip()
            if not content:
                content = (msg.get("reasoning_content") or "").strip()
            # extract JSON object from content (may be wrapped in text or code fence)
            start = content.find("{")
            end = content.rfind("}")
            if start >= 0 and end > start:
                return json.loads(content[start:end + 1])
            return None
        except Exception:
            time.sleep(2)
    return None

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--answers", default="evaluation/answers.jsonl")
    ap.add_argument("--judges", nargs="*", default=["glm-5.3", "qwen3.7-max"])
    ap.add_argument("--out", default="evaluation/judged.jsonl")
    ap.add_argument("--workers", type=int, default=8)
    a = ap.parse_args()

    items = [json.loads(x) for x in Path(a.answers).read_text(encoding="utf-8").splitlines() if x.strip()]
    # incremental output: append each judged item so progress is preserved
    out_path = Path(a.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    done_ids = set()
    if out_path.exists():
        for line in out_path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                try:
                    done_ids.add(json.loads(line)["id"])
                except Exception:
                    pass
    fout = open(out_path, "a", encoding="utf-8")
    out = []
    todo = [it for it in items if it["id"] not in done_ids]
    # judge all (item, system, judge) pairs concurrently
    jobs = []  # (item_index_in_todo, system, judge)
    for ii, it in enumerate(todo):
        for system in it["answers"]:
            for j in a.judges:
                jobs.append((ii, system, j))

    def work(job):
        ii, system, j = job
        it = todo[ii]
        ev_texts = [e["text"] for e in it.get("retrieved_evidence", [])]
        s = call_judge(it["question"], it["gold_answer"], it["answers"][system] or "", ev_texts, j)
        return job, s

    results = [[] for _ in todo]
    with ThreadPoolExecutor(max_workers=a.workers) as ex:
        for job, s in ex.map(work, jobs):
            ii, system, j = job
            if not results[ii]:
                results[ii] = {"id": todo[ii]["id"], "question": todo[ii]["question"],
                               "answerable": todo[ii]["answerable"], "label": todo[ii]["label"],
                               "predicate": todo[ii]["predicate"], "subject": todo[ii]["subject"],
                               "gold_answer": todo[ii]["gold_answer"], "scores": {system: {j: s}}}
            else:
                results[ii]["scores"].setdefault(system, {})[j] = s

    for rec in results:
        if not rec:
            continue
        out.append(rec)
        fout.write(json.dumps(rec, ensure_ascii=False) + "\n"); fout.flush()
        print(f"judged {rec['id']}", flush=True)
    fout.close()

    print(json.dumps({"out": a.out, "items": len(out), "judges": a.judges}, ensure_ascii=False))

if __name__ == "__main__":
    main()
