#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""export_v2_csv.py — 为 Neo4j LOAD CSV 导出生成 CSV（v2 数据 + 评审团共识 + PubChem 链接）。
生成：strict_extraction_v2/*.csv、jury/consensus.csv、strict_extraction_v2/pubchem_links.csv
并把它们复制到 /var/lib/neo4j/import/ 对应子目录（若可写）。
"""
from __future__ import annotations
import csv, json, shutil, subprocess
from pathlib import Path


def dump(rows, path, fields):
    with open(path, 'w', encoding='utf-8', newline='') as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction='ignore')
        w.writeheader()
        for r in rows:
            w.writerow(r)


def jl(p):
    return [json.loads(x) for x in Path(p).read_text(encoding='utf-8').splitlines() if x.strip()]


def main():
    src = Path('strict_extraction_v2')
    jury = Path('jury')

    dump(jl(src / 'documents.jsonl'), src / 'documents.csv',
         ['doc_id', 'path', 'title'])
    dump(jl(src / 'evidence.jsonl'), src / 'evidence.csv',
         ['evidence_id', 'doc_id', 'line_no', 'text'])
    dump(jl(src / 'entities.jsonl'), src / 'entities.csv',
         ['entity_id', 'name', 'type', 'normalized_name', 'status'])
    dump(jl(src / 'mentions.jsonl'), src / 'mentions.csv',
         ['mention_id', 'entity_id', 'evidence_id', 'doc_id', 'text', 'line_no'])
    dump(jl(src / 'values.jsonl'), src / 'values.csv',
         ['value_id', 'evidence_id', 'doc_id', 'value', 'unit', 'slot', 'raw_text', 'status'])
    dump(jl(src / 'relations.jsonl'), src / 'relations.csv',
         ['fact_id', 'subject_id', 'predicate', 'object_id', 'evidence_id', 'doc_id', 'line_no', 'status'])

    cond = jl(src / 'conditions.jsonl')
    for c in cond:
        c.setdefault('value2', '')
        c.setdefault('scope', '')
    dump(cond, src / 'conditions.csv',
         ['cond_id', 'fact_id', 'slot', 'value', 'value2', 'unit', 'raw', 'scope', 'evidence_id', 'doc_id'])

    cons = jl(jury / 'consensus.jsonl')
    for r in cons:
        r['per_model_labels'] = '|'.join(f"{m}={l}" for m, l in r.get('per_model_labels', {}).items())
    dump(cons, jury / 'consensus.csv',
         ['fact_id', 'predicate', 'n_supported', 'panel_decision', 'consensus_label',
          'per_model_labels', 'gold_status'])

    pl = jl(src / 'pubchem_links.jsonl')
    for r in pl:
        pc = r.get('pubchem') or {}
        r['cid'] = pc.get('cid', '')
        r['smiles'] = pc.get('smiles', '')
        r['inchikey'] = pc.get('inchikey', '')
        r['formula'] = pc.get('formula', '')
        r['matched_term'] = r.get('matched_term', '')
    dump(pl, src / 'pubchem_links.csv',
         ['entity_id', 'entity_name', 'status', 'cid', 'smiles', 'inchikey', 'formula', 'matched_term'])

    # 复制到 Neo4j import 目录
    try:
        base = Path('/var/lib/neo4j/import')
        (base / 'strict_extraction_v2').mkdir(parents=True, exist_ok=True)
        (base / 'jury').mkdir(parents=True, exist_ok=True)
        for f in src.glob('*.csv'):
            shutil.copy(f, base / 'strict_extraction_v2' / f.name)
        for f in jury.glob('*.csv'):
            shutil.copy(f, base / 'jury' / f.name)
        print('CSV 已复制到 /var/lib/neo4j/import/')
        subprocess.run(['chown', '-R', 'neo4j:neo4j', str(base / 'strict_extraction_v2'), str(base / 'jury')], check=False)
    except Exception as e:
        print(f'Neo4j import 复制失败（可手动复制）: {e}')

    print('导出完成。')


if __name__ == '__main__':
    main()
