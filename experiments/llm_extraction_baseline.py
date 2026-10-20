#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""对比实验 C：LLM 直接抽取基线。

从证据行中抽样（分层：管线有产出的行 + 随机其余行），由 LLM 按同一 9 谓词
schema 直接抽取三元组与条件，与确定性规则管线对比：
  - 召回（管线事实被 LLM 复现的比例）
  - 命中层次（LLM 三元组匹配 verified / quarantine / rejected / 全新）
  - 双模型一致性
"""
from __future__ import annotations
import argparse, json, os, random, re, time, urllib.request
from pathlib import Path

API_BASE = os.environ.get("RAG_LLM_BASE_URL", "https://api.epicllmrouter.top/v1")
API_KEY = os.environ.get("RAG_LLM_API_KEY", "")

PROMPT = """你是电镀与电化学沉积领域的信息抽取专家。从给定的证据文本行中抽取全部三元组（主体, 谓词, 客体）及实验条件。

谓词集合（仅限以下 9 种）：
- used_as_leveler：X 被用作整平剂（leveler）
- used_as_suppressor：X 被用作抑制剂/载体/润湿剂（suppressor）
- used_as_accelerator：X 被用作加速剂（accelerator/brightener）
- used_as_inhibitor：X 被用作抑制剂（inhibitor，抑制语境）
- inhibits_deposition：X 抑制金属沉积/电化学沉积
- accelerates_deposition：X 加速金属沉积/电化学沉积
- improves_filling：X 改善（通孔/盲孔/沟槽）填充
- synergizes_with：X 与 Y 协同/配合作用
- adsorbs_on：X 吸附于电极/表面

硬性约束：
1) 主体必须是化学物质、添加剂或材料（CuSO4、SPS、PEG、Cl- 等）；
2) 关系必须在该行文本中明确表述，不得推断；
3) 抑制/加速必须针对金属沉积本身（促进析氢不算）；
4) 改善填充必须有填充语境（通孔、盲孔、填充率、超共形）；
5) 条件槽仅限：concentration, potential, temperature, current_density, pH, rotation, time, geometry, additive_role。

仅输出 JSON（不要其他文字）：
{"triples": [{"subject": "...", "predicate": "谓词英文", "object": "...", "conditions": {"槽名": "值+单位"}}]}
无可抽取三元组时输出 {"triples": []}。"""


def call_llm(line_text, model):
    body = json.dumps({
        "model": model, "temperature": 0, "max_tokens": 4000,
        "messages": [
            {"role": "user", "content": PROMPT + "\n\n证据文本行：\n" + line_text},
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
            content = (msg.get("content") or msg.get("reasoning_content") or "").strip()
            content = re.sub(r"^```(?:json)?\s*|\s*```$", "", content)  # 去代码栅栏
            m = re.search(r"\{.*\}", content, re.S)
            if not m:
                return {"triples": [], "parse_error": True}
            parsed = json.loads(m.group(0))
            # 裁剪截断的最后一个元素（finish_reason=length 时数组常断在中间）
            return parsed
        except Exception:
            time.sleep(2)
    return {"triples": [], "error": True}


def norm(s):
    s = (s or "").strip()
    return s if s.isupper() or not any(c.isalpha() for c in s) else s.lower()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--index", default="rag_index_v2")
    ap.add_argument("--relations", default="strict_extraction_v2/relations.jsonl")
    ap.add_argument("--jury", default="jury/consensus.jsonl")
    ap.add_argument("--models", nargs="*", default=["glm-5.3", "kimi-k2.6"])
    ap.add_argument("--n-positive", type=int, default=100)
    ap.add_argument("--n-other", type=int, default=50)
    ap.add_argument("--seed", type=int, default=2025)
    ap.add_argument("--out", default="evaluation/llm_extraction_baseline.jsonl")
    ap.add_argument("--redo", nargs="*", default=[],
                    help="强制重跑的模型（忽略已有结果）")
    a = ap.parse_args()

    index_json = Path(a.index) / "index.json"
    rows = (json.loads(index_json.read_text(encoding="utf-8")) if index_json.is_file()
            else json.loads(Path(a.index).read_text(encoding="utf-8")))["rows"]
    rels = [json.loads(x) for x in Path(a.relations).read_text(encoding="utf-8").splitlines() if x.strip()]
    jury = {r["fact_id"]: r for r in (json.loads(x) for x in Path(a.jury).read_text(encoding="utf-8").splitlines() if x.strip())}

    row_by_id = {r["evidence_id"]: r for r in rows}
    fact_evs = {}
    for r in rels:
        subj = r.get("subject_name") or ""
        obj = r.get("object_name") or ""
        fact_evs.setdefault(r["evidence_id"], []).append({
            "subject": subj, "predicate": r["predicate"], "object": obj,
            "decision": jury.get(r["fact_id"], {}).get("panel_decision", "?"),
        })
    pos_evs = [e for e in fact_evs if e in row_by_id]
    other_evs = [r["evidence_id"] for r in rows if r["evidence_id"] not in fact_evs]

    rng = random.Random(a.seed)
    sample = (rng.sample(pos_evs, min(a.n_positive, len(pos_evs)))
              + rng.sample(other_evs, min(a.n_other, len(other_evs))))
    print(json.dumps({"positive_lines": len(pos_evs), "other_lines": len(other_evs),
                      "sampled": len(sample)}, ensure_ascii=False), flush=True)

    out = []
    prior = {}
    if Path(a.out).exists():  # 断点续跑：保留已有模型结果
        for r in (json.loads(x) for x in Path(a.out).read_text(encoding="utf-8").splitlines() if x.strip()):
            prior[r["evidence_id"]] = r
    for ev_id in sample:
        text = row_by_id[ev_id]["text"]
        llm_res = {}
        if ev_id in prior:  # 已有该模型的结果则跳过（--redo 的除外）
            for m in a.models:
                if m in a.redo:
                    continue
                if prior[ev_id]["llm"].get(m):
                    llm_res[m] = prior[ev_id]["llm"][m]
        for m in a.models:
            if m in llm_res:
                continue
            llm_res[m] = call_llm(text, m)
        rec = {"evidence_id": ev_id, "text": text,
               "pipeline_facts": fact_evs.get(ev_id, []),
               "llm": llm_res}
        out.append(rec)
        print(f"done {ev_id[:16]} ({len(out)}/{len(sample)})", flush=True)
    Path(a.out).write_text("\n".join(json.dumps(x, ensure_ascii=False) for x in out) + "\n", encoding="utf-8")
    print(json.dumps({"out": a.out, "lines": len(out), "models": a.models}, ensure_ascii=False))


if __name__ == "__main__":
    main()
