#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""gold_unified_builder.py — 统一两代 gold 评测集为单一 schema。

本仓库现存两份 gold 真值（统一方案断点 G6）：
  v1  golden_benchmark/gold_test.jsonl      24 条，gpt-5.6 单模型判定，
      谓词级协议（有已知效度缺陷），数据层 strict_extraction_verify；
  v2  golden_benchmark_v2/gold_test.jsonl   44 条，五模型评审团共识，
      三元组级协议，数据层 strict_extraction_v2 + jury 共识。

本脚本将两者映射为统一 QA schema，使 rag_gold_retrieval_eval.py /
rag_answer_eval.py / rag_judge.py 等下游评测链路对两代真值完全同构：

  id, question, answerable, question_type(factual|adversarial|partial|ambiguous),
  gold_answer, gold_evidence_ids, fact_id, evidence_id, predicate, subject,
  object, conditions, conditions_struct, label, panel_decision, gold_version,
  gold_status, gold_source, surface_text

映射规则（v2，label×decision 双轨制）：
  consensus_label=supported                       → factual（30：verified 24 + quarantine 6）
  consensus_label=partial                         → partial（3，answerable 但单列统计）
  consensus_label in (unsupported, contradicted)  → adversarial（10，探针）
  consensus_label=ambiguous                       → ambiguous（1，不计入主指标）
v1：supported→factual，unsupported/contradicted→adversarial。

用法：
  python3 gold_unified_builder.py                # 生成三份输出
  python3 gold_unified_builder.py --v2-gold golden_benchmark_v2/gold_test.jsonl ...
"""
from __future__ import annotations
import argparse, json
from collections import Counter
from pathlib import Path

REL_ZH = {
    "inhibits_deposition": "抑制沉积",
    "accelerates_deposition": "加速沉积",
    "synergizes_with": "与…协同",
    "improves_filling": "改善填充",
    "used_as_leveler": "被用作整平剂",
    "used_as_suppressor": "被用作抑制剂",
    "used_as_accelerator": "被用作加速剂",
    "used_as_inhibitor": "被用作抑制剂",
    "adsorbs_on": "吸附于电极表面",
}


def craft_question(pred, subj, obj):
    if pred == "inhibits_deposition":
        return f"{subj}对{obj}有什么作用？它是抑制沉积吗？"
    if pred == "accelerates_deposition":
        return f"{subj}对{obj}有什么作用？它会加速沉积吗？"
    if pred == "synergizes_with":
        return f"{subj}和{obj}之间有什么相互作用？"
    if pred == "improves_filling":
        return f"{subj}对{obj}有什么影响？它能改善填充效果吗？"
    if pred == "used_as_leveler":
        return f"{subj}在电镀体系中起什么作用？它被用作整平剂吗？"
    if pred == "used_as_suppressor":
        return f"{subj}在电镀体系中起什么作用？它被用作抑制剂吗？"
    if pred == "used_as_accelerator":
        return f"{subj}在电镀体系中起什么作用？它被用作加速剂吗？"
    if pred == "used_as_inhibitor":
        return f"{subj}在电镀体系中起什么作用？它被用作抑制剂（inhibitor）吗？"
    if pred == "adsorbs_on":
        return f"{subj}在电极表面有什么行为？它会吸附在电极表面吗？"
    return f"{subj}对{obj}有什么作用？"


def fmt_cond_struct(conds):
    """v2 consensus_conditions: [{slot,value,unit,votes,sources}] -> (文本列表, 原始结构)"""
    out_txt, out_struct = [], []
    for c in conds or []:
        if not isinstance(c, dict):
            continue
        unit = c.get("unit") or ""
        v = str(c.get("value", ""))
        if c.get("value2"):
            v += f"–{c['value2']}"
        out_txt.append(f"{c.get('slot','')}={v} {unit}".strip())
        out_struct.append({"slot": c.get("slot"), "value": v, "unit": unit,
                           "votes": c.get("votes"), "sources": c.get("sources")})
    return out_txt, out_struct


def craft_gold_answer(pred, subj, obj, cond_txts, panel=None):
    base = {
        "inhibits_deposition": f"{subj}在相应条件下抑制{obj}。",
        "accelerates_deposition": f"{subj}在相应条件下加速{obj}。",
        "synergizes_with": f"{subj}与{obj}存在协同作用。",
        "improves_filling": f"{subj}在相应条件下改善{obj}。",
        "used_as_leveler": f"{subj}在电镀体系中被用作整平剂。",
        "used_as_suppressor": f"{subj}在电镀体系中被用作抑制剂。",
        "used_as_accelerator": f"{subj}在电镀体系中被用作加速剂。",
        "used_as_inhibitor": f"{subj}在电镀体系中被用作抑制剂（inhibitor）。",
        "adsorbs_on": f"{subj}吸附于电极表面。",
    }.get(pred, f"{subj}与{obj}存在{REL_ZH.get(pred, pred)}关系。")
    if cond_txts:
        base += "关键条件：" + "；".join(cond_txts[:6]) + "。"
    return base


def build_v1(args):
    """v1: golden_benchmark/gold_test.jsonl + strict_extraction_verify（保持既有口径）"""
    gold = [json.loads(x) for x in Path(args.v1_gold).read_text(encoding="utf-8").splitlines() if x.strip()]
    rel = {r["fact_id"]: r for r in (json.loads(x) for x in Path(args.v1_relations).read_text(encoding="utf-8").splitlines() if x.strip())}
    ent = {e["entity_id"]: e for e in (json.loads(x) for x in Path(args.v1_entities).read_text(encoding="utf-8").splitlines() if x.strip())}
    out = []
    for g in gold:
        r = rel.get(g["fact_id"])
        if not r:
            continue
        subj_name = ent.get(r["subject_id"], {}).get("name", "")
        obj_name = ent.get(r["object_id"], {}).get("name", "")
        subj, obj = g["subject"] or subj_name, g["object"] or obj_name
        answerable = g["label"] == "supported"
        qtype = "factual" if answerable else "adversarial"
        q = craft_question(r["predicate"], subj, obj)
        if answerable:
            conds = [c for c in g.get("conditions", []) if c]
            ans = craft_gold_answer(r["predicate"], subj, obj, conds)
        else:
            reason = (g.get("reason") or "").strip()
            ans = f"不能支持该说法。{reason}"
        out.append({
            "id": f"goldv1_{g['fact_id'][:8]}",
            "question": q,
            "answerable": answerable,
            "question_type": qtype,
            "gold_answer": ans,
            "gold_evidence_ids": [g["evidence_id"]],
            "fact_id": g["fact_id"],
            "evidence_id": g["evidence_id"],
            "predicate": r["predicate"],
            "original_predicate": g.get("original_predicate"),
            "subject": subj,
            "object": obj,
            "conditions": [c for c in g.get("conditions", []) if c],
            "conditions_struct": [],
            "label": g["label"],
            "panel_decision": None,
            "gold_version": "v1",
            "gold_status": g.get("gold_status"),
            "gold_source": g.get("gold_source"),
            "surface_text": r.get("surface_text", ""),
        })
    return out


def build_v2(args):
    """v2: golden_benchmark_v2/gold_test.jsonl（五模型评审团共识，三元组级）"""
    import ast as _ast
    gold = [json.loads(x) for x in Path(args.v2_gold).read_text(encoding="utf-8").splitlines() if x.strip()]
    rel = {r["fact_id"]: r for r in (json.loads(x) for x in Path(args.v2_relations).read_text(encoding="utf-8").splitlines() if x.strip())}
    ent = {e["entity_id"]: e for e in (json.loads(x) for x in Path(args.v2_entities).read_text(encoding="utf-8").splitlines() if x.strip())}
    # 全量评审团事实：对抗探针有效性审计 + 补充数据源。
    # 有效性约束：对抗题源自被拒三元组，但若同 (主体, 谓词) 在语料中存在已验证
    # 事实（被拒仅因客体槽抽取错误），则该自然语言问题并非真正的不可支持断言，
    # 会系统性冤枉正确回答的模型 —— 必须剔除。
    cons = [json.loads(x) for x in Path("jury/consensus.jsonl").read_text(encoding="utf-8").splitlines() if x.strip()]
    cons_by_fact = {c["fact_id"]: c for c in cons}
    verified_sp = {(c["subject_name"], c["predicate"]) for c in cons if c.get("panel_decision") == "verified"}
    test_fact_ids = {g["fact_id"] for g in gold}

    def _parse(x):
        if isinstance(x, (list, dict)) or x is None: return x
        try: return _ast.literal_eval(x) if x else None
        except Exception: return None

    def make_record(fact_id, subj, obj, pred, label, decision, evidence_id,
                    n_supported, corrected, conditions, surface_text, gold_status):
        q = craft_question(pred, subj, obj)
        cond_txts, cond_struct = fmt_cond_struct(conditions)
        if label == "partial":
            flaw = ""
            if isinstance(corrected, dict) and corrected:
                flaw = "多数模型建议修正：" + "，".join(f"{k}→{v}" for k, v in corrected.items())
            ans = (f"证据部分支持该说法（{n_supported}/5 模型支持）。{flaw}")
        elif label in ("unsupported", "contradicted"):
            fix = ""
            if isinstance(corrected, dict) and corrected:
                fix = "评审团建议的正确表述：" + "，".join(f"{k}={v}" for k, v in corrected.items()) + "。"
            ans = (f"不能支持该说法。五模型评审团仅 {n_supported}/5 支持，"
                   f"共识为 {label}。{fix}")
        else:
            ans = craft_gold_answer(pred, subj, obj, cond_txts)
        return {
            "id": f"goldv2_{fact_id[:8]}",
            "question": q,
            "answerable": label in ("supported", "partial"),
            "question_type": ("factual" if label == "supported" else
                              "partial" if label == "partial" else
                              "adversarial" if label in ("unsupported", "contradicted") else "ambiguous"),
            "gold_answer": ans,
            "gold_evidence_ids": [evidence_id],
            "fact_id": fact_id,
            "evidence_id": evidence_id,
            "predicate": pred,
            "original_predicate": None,
            "subject": subj,
            "object": obj,
            "conditions": [c for c in (cond_txts or []) if c],
            "conditions_struct": cond_struct or [],
            "label": label,
            "panel_decision": decision,
            "gold_version": "v2",
            "gold_status": gold_status,
            "gold_source": "five_model_panel_consensus",
            "surface_text": surface_text,
        }

    out = []
    used_fact_ids = set()
    skipped_invalid = 0
    for g in gold:
        r = rel.get(g["fact_id"])
        if not r:
            continue
        subj = g.get("subject_name") or ent.get(r["subject_id"], {}).get("name", "")
        obj = g.get("object_name") or ent.get(r["object_id"], {}).get("name", "")
        pred = r["predicate"]
        label = g["consensus_label"]
        decision = g.get("panel_decision")
        if label in ("unsupported", "contradicted") and (subj, pred) in verified_sp:
            skipped_invalid += 1
            continue  # 无效对抗探针：同(主体,谓词)在语料中有已验证事实
        rec = make_record(g["fact_id"], subj, obj, pred, label, decision,
                          g["evidence_id"], g.get("n_supported", "?"),
                          g.get("corrected_majority") if isinstance(g.get("corrected_majority"), dict) else _parse(g.get("corrected_majority")),
                          g.get("consensus_conditions"), g.get("surface_text") or r.get("surface_text", ""),
                          g.get("gold_status"))
        out.append(rec)
        used_fact_ids.add(g["fact_id"])

    # 对抗探针补充：从被拒事实池中选取 (主体,谓词) 无已验证支持的有效探针，
    # 测试划分内优先，(主体,谓词) 多样化，补足至目标数。
    TARGET_ADV = 8
    adv_sp = {(r["subject"], r["predicate"]) for r in out if r["question_type"] == "adversarial"}
    cands = [c for c in cons
             if c.get("panel_decision") == "rejected"
             and c.get("consensus_label") in ("unsupported", "contradicted")
             and (c["subject_name"], c["predicate"]) not in verified_sp
             and c["fact_id"] not in used_fact_ids]
    cands.sort(key=lambda c: (c["fact_id"] not in test_fact_ids,
                              (c["subject_name"], c["predicate"]) in adv_sp))
    topped = 0
    for c in cands:
        if sum(1 for r in out if r["question_type"] == "adversarial") >= TARGET_ADV:
            break
        sp = (c["subject_name"], c["predicate"])
        if sp in adv_sp:
            continue
        out.append(make_record(c["fact_id"], c["subject_name"], c["object_name"], c["predicate"],
                               c["consensus_label"], c["panel_decision"], c["evidence_id"],
                               c.get("n_supported", "?"), _parse(c.get("corrected_majority")),
                               _parse(c.get("consensus_conditions")), c.get("surface_text", ""),
                               c.get("gold_status")))
        used_fact_ids.add(c["fact_id"]); adv_sp.add(sp); topped += 1
    print(json.dumps({"skipped_invalid_adversarial": skipped_invalid,
                      "adversarial_topped_up": topped}, ensure_ascii=False))
    return out


def merge_by_question(rows):
    """按 (question, question_type) 聚合为多 gold 条目。

    v2 中同一 (subject, predicate, object) 组合可能对应多条事实/多条证据；
    对检索评测而言这些证据都是有效 gold（与 silver entity 集的开放式多 gold
    语义一致）。聚合后顶层保留组内最高置信事实的冗余字段（兼容
    rag_answer_eval.py / rag_judge.py 的字段访问），明细保留在 facts 列表。
    """
    groups = {}
    order = {"verified": 0, "quarantine": 1, "rejected": 2, None: 3}
    for r in rows:
        key = (r["question"], r["question_type"])
        groups.setdefault(key, []).append(r)
    out = []
    for (q, qt), items in groups.items():
        items.sort(key=lambda r: order.get(r.get("panel_decision"), 3))
        head = items[0]
        merged = dict(head)
        merged["gold_evidence_ids"] = sorted({e for it in items for e in it["gold_evidence_ids"]})
        merged["n_gold_facts"] = len(items)
        merged["facts"] = [
            {k: it[k] for k in ("fact_id", "evidence_id", "predicate", "subject",
                                "object", "label", "panel_decision", "conditions",
                                "gold_answer") if k in it}
            for it in items
        ]
        out.append(merged)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--v1-gold", default="golden_benchmark/gold_test.jsonl")
    ap.add_argument("--v1-relations", default="strict_extraction_verify/relations.jsonl")
    ap.add_argument("--v1-entities", default="strict_extraction_verify/entities.jsonl")
    ap.add_argument("--v2-gold", default="golden_benchmark_v2/gold_test.jsonl")
    ap.add_argument("--v2-relations", default="strict_extraction_v2/relations.jsonl")
    ap.add_argument("--v2-entities", default="strict_extraction_v2/entities.jsonl")
    ap.add_argument("--out-v1", default="evaluation/gold_qa_v1.jsonl")
    ap.add_argument("--out-v2", default="evaluation/gold_qa_v2.jsonl")
    ap.add_argument("--out-unified", default="evaluation/gold_qa_unified.jsonl")
    a = ap.parse_args()

    v1 = build_v1(a)
    v2 = build_v2(a)
    v1m = merge_by_question(v1)
    v2m = merge_by_question(v2)
    unified = v1m + v2m

    for path, rows in [(a.out_v1, v1m), (a.out_v2, v2m), (a.out_unified, unified)]:
        p = Path(path); p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("\n".join(json.dumps(x, ensure_ascii=False) for x in rows) + "\n", encoding="utf-8")

    def stat(rows):
        return {"items": len(rows), "types": dict(Counter(x["question_type"] for x in rows)),
                "multi_gold": sum(1 for x in rows if x["n_gold_facts"] > 1),
                "total_gold_evidence": sum(len(x["gold_evidence_ids"]) for x in rows)}
    report = {
        "v1": {**stat(v1m), "predicates": dict(Counter(x["predicate"] for x in v1m)),
               "gold_status": v1m[0]["gold_status"] if v1m else None},
        "v2": {**stat(v2m), "predicates": dict(Counter(x["predicate"] for x in v2m)),
               "decisions": dict(Counter(x["panel_decision"] for x in v2m if x["panel_decision"])),
               "gold_status": v2m[0]["gold_status"] if v2m else None},
        "unified_items": len(unified),
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
