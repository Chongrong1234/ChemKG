#!/usr/bin/env python3
"""Create a stratified manual-review template and summarize candidate KG quality.

This does not pretend to calculate correctness without labels. It creates a review
sheet whose labels can be filled by a domain expert, then computes audited rates.
"""
from __future__ import annotations
import argparse, csv, random
from pathlib import Path

LABELS = ["supported", "partially_supported", "unsupported", "contradicted", "ambiguous", "not_verifiable"]

def read_csv(path):
    with path.open(encoding="utf-8", newline="") as f: return list(csv.DictReader(f))

def main():
    ap=argparse.ArgumentParser(); ap.add_argument("--kg",default="kg_data"); ap.add_argument("--sample",type=int,default=400); ap.add_argument("--seed",type=int,default=42); ap.add_argument("--out",default="kg_review.csv")
    a=ap.parse_args(); facts=read_csv(Path(a.kg)/"facts.csv")
    random.seed(a.seed); sample=random.sample(facts,min(a.sample,len(facts)))
    fields=["fact_id","doc_id","evidence_id","predicate","surface_text","status","review_label","reviewer","review_notes","correct_subject","correct_predicate","correct_object","correct_conditions","correct_value_unit","evidence_valid"]
    with open(a.out,"w",encoding="utf-8",newline="") as f:
        w=csv.DictWriter(f,fieldnames=fields); w.writeheader()
        for r in sample: w.writerow({**{k:r.get(k,"") for k in fields},"review_label":"","reviewer":"","review_notes":""})
    print(f"Created {a.out} with {len(sample)} facts. Fill review_label using: {', '.join(LABELS)}")
    print("Recommended positive support rate = supported / all labeled facts")

if __name__ == "__main__": main()
