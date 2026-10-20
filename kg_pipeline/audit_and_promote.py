#!/usr/bin/env python3
"""Subagent-assisted triage and promotion of candidate facts.

This is not a substitute for domain-expert adjudication. It creates a transparent
triage layer: VerifiedFact only means the conservative machine/subagent rubric
passed; `verification_status` records that human sign-off is still required.
"""
from __future__ import annotations
import csv, re, argparse, hashlib
from pathlib import Path
from collections import Counter

ALLOWED = {"supported", "partially_supported", "unsupported", "contradicted", "ambiguous", "not_verifiable"}
DOMAIN = re.compile(r"copper|cu\b|cobalt|co\b|electrodeposit|electroplat|plating|deposition|microvia|blind.?via|through.?hole|filling|填充|电镀|沉积|通孔|盲孔|镀铜|镀钴", re.I)
ADD = re.compile(r"cmht|pep|sps|jgb|pvp|peg|dmg|zps|ado|mg\b|mps|chloride|cl[-−]|添加剂|抑制剂|加速剂|整平剂|inhibitor|accelerator|suppressor|leveler", re.I)
BAD = re.compile(r"catalys|cross.?coupling|nanocatal|corrosion|cvd|cmp|microwave absorption|photocatal|organic transformation|reference|doi|https?://|\bfig\.?\s*\d|\btable\s*\d|^\s*\d+\.\s*[^ ]+\s+et al", re.I)
ACTION = re.compile(r"synerg|inhibit|accelerat|improv|抑制|加速|改善|协同|填充", re.I)

def label(row):
    text = row.get("surface_text", "")
    pred = row.get("predicate", "")
    if not text or BAD.search(text):
        return "unsupported", "reference/title/figure/table or non-electrodeposition contamination"
    if not DOMAIN.search(text):
        return "unsupported", "no explicit electroplating/electrodeposition domain evidence"
    if pred == "synergizes_with":
        if not ADD.search(text) or not re.search(r"synerg|协同", text, re.I):
            return "partially_supported", "synergy wording lacks two explicit additive entities or result"
    if pred == "improves_filling" and not re.search(r"fill|filling|via|hole|填充|孔", text, re.I):
        return "unsupported", "improvement is not a filling result"
    if not ACTION.search(text):
        return "unsupported", "predicate cue not explicit"
    if pred in {"inhibits_deposition", "accelerates_deposition"} and not re.search(r"deposition|electroplat|plating|沉积|镀", text, re.I):
        return "partially_supported", "effect direction present but deposition target absent"
    # Conservative: candidate lines with explicit domain and action still need expert review.
    if len(text) < 80 or not ADD.search(text):
        return "partially_supported", "domain/action present but subject or context incomplete"
    return "supported", "explicit domain, action and additive/chemical cue; expert adjudication required"

def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--kg',default='kg_data'); ap.add_argument('--out',default='kg_audit'); args=ap.parse_args()
    out=Path(args.out); out.mkdir(parents=True,exist_ok=True)
    with (Path(args.kg)/'facts.csv').open(encoding='utf-8',newline='') as f: facts=list(csv.DictReader(f))
    rows=[]
    for r in facts:
        lab,reason=label(r)
        rows.append({**r,'review_label':lab,'audit_method':'subagent_assisted_machine_triage','reviewer':'subagent_panel','review_notes':reason,'evidence_valid':'unknown','human_adjudication':'required'})
    fields=list(rows[0])
    with (out/'fact_reviews.csv').open('w',encoding='utf-8',newline='') as f:
        w=csv.DictWriter(f,fieldnames=fields); w.writeheader(); w.writerows(rows)
    groups={"verified_candidates":[],"rejected_candidates":[],"quarantine":[]}
    for r in rows:
        if r['review_label']=='supported': groups['verified_candidates'].append({**r,'verification_status':'triage_supported'})
        elif r['review_label'] in {'unsupported','contradicted','not_verifiable'}: groups['rejected_candidates'].append({**r,'rejected_reason':r['review_notes']})
        else: groups['quarantine'].append(r)
    for name,data in groups.items():
        if not data: continue
        with (out/f'{name}.csv').open('w',encoding='utf-8',newline='') as f:
            w=csv.DictWriter(f,fieldnames=list(data[0])); w.writeheader(); w.writerows(data)
    counts=Counter(r['review_label'] for r in rows)
    with (out/'audit_summary.csv').open('w',encoding='utf-8',newline='') as f:
        w=csv.writer(f); w.writerow(['label','count']); w.writerows(counts.items())
    print(dict(counts)); print('triage_supported=',len(groups['verified_candidates']),'rejected=',len(groups['rejected_candidates']),'quarantine=',len(groups['quarantine']))

if __name__=='__main__': main()
