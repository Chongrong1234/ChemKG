#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""对比实验 A：无检索闭卷基线（closed-book）。

4 个 LLM 直接回答基准测试集问题（不提供任何证据），由相同裁判协议评分，
用于度量 RAG 检索环节的接地价值。输出与 rag_judge.py 兼容。
"""
from __future__ import annotations
import argparse, json, os, time, urllib.request
from pathlib import Path

API_BASE = os.environ.get("RAG_LLM_BASE_URL", "https://api.epicllmrouter.top/v1")
API_KEY = os.environ.get("RAG_LLM_API_KEY", "")

SYS_PROMPT = (
    "你是电镀与电化学沉积领域的专家。请仅根据你已有的专业知识回答问题："
    "1) 明确回答问题中的关系（抑制/加速/协同/改善填充/整平/吸附）；"
    "2) 如涉及实验条件（浓度、温度、电流密度、pH、电位、转速）请保留；"
    "3) 不确定或不知道时，明确说明不确定，不要编造；"
    "4) 不编造数值与文献引用。回答控制在 150 字内。"
)

def llm_answer(question, model):
    if not API_KEY:
        return None
    body = json.dumps({
        "model": model, "temperature": 0, "max_tokens": 600,
        "messages": [
            {"role": "system", "content": SYS_PROMPT},
            {"role": "user", "content": f"问题：{question}"},
        ],
    }, ensure_ascii=False).encode()
    req = urllib.request.Request(
        API_BASE.rstrip("/") + "/chat/completions", data=body,
        headers={"Content-Type": "application/json", "Authorization": "Bearer " + API_KEY})
    last_err = None
    for _ in range(3):
        try:
            with urllib.request.urlopen(req, timeout=120) as resp:
                data = json.loads(resp.read())
            content = data["choices"][0]["message"].get("content") or ""
            if not content.strip():
                content = data["choices"][0]["message"].get("reasoning_content") or ""
            return content
        except Exception as e:
            last_err = e
            time.sleep(2)
    return f"[LLM error: {type(last_err).__name__}]"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--gold", default="evaluation/gold_qa_v2.jsonl")
    ap.add_argument("--models", nargs="*", default=["glm-5.3", "qwen3.7-max", "deepseek-v4-pro-0813", "kimi-k2.6"])
    ap.add_argument("--out", default="evaluation/v2_answers_closedbook.jsonl")
    a = ap.parse_args()

    gold = [json.loads(x) for x in Path(a.gold).read_text(encoding="utf-8").splitlines() if x.strip()]
    out = []
    for g in gold:
        answers = {}
        for m in a.models:
            answers[m] = llm_answer(g["question"], m)
        out.append({
            "id": g["id"], "question": g["question"], "answerable": g["answerable"],
            "label": g.get("label"), "predicate": g.get("predicate"), "subject": g.get("subject"),
            "gold_answer": g["gold_answer"], "gold_evidence_ids": g.get("gold_evidence_ids", []),
            "retrieved_evidence": [],  # 闭卷：无检索
            "answers": answers,
        })
        print(f"done {g['id']} (closed-book)", flush=True)
    p = Path(a.out)
    p.write_text("\n".join(json.dumps(x, ensure_ascii=False) for x in out) + "\n", encoding="utf-8")
    print(json.dumps({"out": str(p), "items": len(out), "models": a.models}, ensure_ascii=False))


if __name__ == "__main__":
    main()
