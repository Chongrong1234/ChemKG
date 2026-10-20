#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""jury_aggregate.py — 五模型评审团共识聚合与统计。

输出：
  jury/consensus.jsonl          每条事实的逐模型判定、投票、共识标签、裁决
  jury/verified_facts.jsonl     共识支持（含修正后）的事实 → 待人工签核的"准 golden"
  jury/quarantine_facts.jsonl   3/5 支持或有分歧 → 人工复核队列
  jury/rejected_facts.jsonl     ≤2/5 支持或 ≥2 条 contradicted
  jury/human_review_packet.csv  人工签核包（quarantine 全量 + 分层抽样）
  jury/agreement_summary.json   Fleiss' κ、成对 Cohen's κ、Wilson CI、逐模型统计
  golden_benchmark_v2/          共识版 golden 基准（8:2, seed=2025）
"""
from __future__ import annotations
import argparse, csv, json, math, random, re
from pathlib import Path
from collections import Counter, defaultdict

LABELS = ['supported', 'partial', 'unsupported', 'contradicted', 'ambiguous']


def wilson_ci(k, n, z=1.96):
    if n == 0:
        return 0.0, 0.0, 0.0
    p = k / n
    d = 1 + z * z / n
    c = p + z * z / (2 * n)
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return p, max(0.0, (c - h) / d), min(1.0, (c + h) / d)


def fleiss_kappa(rows):
    """rows: List[List[label]]（每行一个事实、每个评审一列）"""
    N = len(rows)
    k = len(rows[0]) if rows else 0
    if N == 0 or k < 2:
        return None
    cats = sorted({l for r in rows for l in r})
    table = [[r.count(c) for c in cats] for r in rows]
    P_i = [(sum(n * n for n in row) - k) / (k * (k - 1)) if k > 1 else 0 for row in table]
    Pbar = sum(P_i) / N
    col_tot = [sum(row[j] for row in table) for j in range(len(cats))]
    Pe = sum((t / (N * k)) ** 2 for t in col_tot)
    return (Pbar - Pe) / (1 - Pe) if Pe < 1 else 1.0


def cohen_kappa(a, b):
    n = len(a)
    if n == 0:
        return None
    ca, cb = Counter(a), Counter(b)
    cats = sorted(set(a) | set(b))
    po = sum(1 for x, y in zip(a, b) if x == y) / n
    pe = sum((ca[c] / n) * (cb[c] / n) for c in cats)
    return (po - pe) / (1 - pe) if pe < 1 else 1.0


def load_reviews(jury_dir: Path):
    by_fact = defaultdict(dict)   # fact_id -> model -> record
    for f in sorted(jury_dir.glob('reviews__*.jsonl')):
        for line in f.read_text(encoding='utf-8').splitlines():
            if not line.strip():
                continue
            try:
                rec = json.loads(line)
            except Exception:
                continue
            if rec.get('label') and rec.get('model'):
                by_fact[rec['fact_id']][rec['model']] = rec
    return by_fact


def merge_conditions(fact, model_records):
    """管线条件 + 模型条件合并：出现 ≥2 来源或管线自身即保留，附票数。"""
    votes = defaultdict(lambda: {'n': 0, 'sources': set()})
    for cd in fact.get('conditions', []):
        key = (cd.get('slot'), str(cd.get('value')), cd.get('unit'))
        votes[key]['n'] += 1
        votes[key]['sources'].add('pipeline')
    for rec in model_records:
        for cd in (rec.get('conditions') or []):
            if not isinstance(cd, dict) or not cd.get('slot'):
                continue
            key = (cd.get('slot'), str(cd.get('value')), cd.get('unit'))
            votes[key]['n'] += 1
            votes[key]['sources'].add(rec.get('model'))
    out = []
    for (slot, value, unit), v in sorted(votes.items()):
        if v['n'] >= 2 or 'pipeline' in v['sources']:
            out.append({'slot': slot, 'value': value, 'unit': unit,
                        'votes': v['n'], 'sources': sorted(v['sources'])})
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--facts', default='strict_extraction_v2/relations.jsonl')
    ap.add_argument('--jury', default='jury')
    ap.add_argument('--golden-out', default='golden_benchmark_v2')
    ap.add_argument('--seed', type=int, default=2025)
    a = ap.parse_args()

    facts = {f['fact_id']: f for f in
             (json.loads(x) for x in Path(a.facts).read_text(encoding='utf-8').splitlines() if x.strip())}
    by_fact = load_reviews(Path(a.jury))
    models = sorted({m for recs in by_fact.values() for m in recs})
    k = len(models)
    print(f'facts={len(facts)} 评审模型数={k}: {models}')

    rows5, rows2 = [], []
    consensus_records, verified, quarantine, rejected, incomplete = [], [], [], [], []
    per_model_supported = Counter()
    per_model_total = Counter()
    pairwise = defaultdict(list)

    for fid, fact in facts.items():
        recs = by_fact.get(fid, {})
        missing = [m for m in models if m not in recs]
        err = [m for m in models if recs.get(m, {}).get('label') == 'api_error']
        labels = [recs[m].get('label') for m in models if m in recs and recs[m].get('label') != 'api_error']
        if missing or err or not labels:
            incomplete.append({'fact_id': fid, 'missing': missing, 'api_error': err})
            continue

        rows5.append(labels)
        rows2.append(['supported' if l == 'supported' else 'not_supported' for l in labels])
        for m, l in zip(models, labels):
            per_model_total[m] += 1
            if l == 'supported':
                per_model_supported[m] += 1
        for i in range(k):
            for j in range(i + 1, k):
                pairwise[(models[i], models[j])].append((labels[i], labels[j]))

        n_sup = labels.count('supported')
        n_con = labels.count('contradicted')
        subj_ok = sum(1 for m in models if recs[m].get('subject_correct') is True)
        obj_ok = sum(1 for m in models if recs[m].get('object_correct') is True)
        pred_ok = sum(1 for m in models if recs[m].get('predicate_correct') is True)
        lab_counts = Counter(labels)
        consensus_label = lab_counts.most_common(1)[0][0]

        corrected = {}
        for comp in ('subject', 'predicate', 'object'):
            votes = Counter()
            for m in models:
                c = recs[m].get('corrected_' + comp)
                if c:
                    votes[str(c)] += 1
            if votes:
                corrected[comp] = votes.most_common(1)[0][0]

        if n_con >= 2:
            decision = 'rejected'
        elif n_sup >= 4 and subj_ok >= 3 and obj_ok >= 3 and pred_ok >= 3:
            decision = 'verified'
        elif n_sup >= 4:
            decision = 'verified_with_correction'
        elif n_sup == 3:
            decision = 'quarantine'
        else:
            decision = 'rejected'

        rec = {
            'fact_id': fid, 'subject_name': fact.get('subject_name'), 'predicate': fact['predicate'],
            'object_name': fact.get('object_name'), 'evidence_id': fact.get('evidence_id'),
            'surface_text': fact.get('surface_text'), 'doc_id': fact.get('doc_id'),
            'per_model_labels': {m: recs[m].get('label') for m in models},
            'model_confidences': {m: recs[m].get('confidence') for m in models},
            'subject_ok_votes': subj_ok, 'object_ok_votes': obj_ok, 'predicate_ok_votes': pred_ok,
            'n_supported': n_sup, 'n_contradicted': n_con, 'consensus_label': consensus_label,
            'panel_decision': decision, 'corrected_majority': corrected,
            'model_reasons': {m: recs[m].get('reason') for m in models},
            'consensus_conditions': merge_conditions(fact, [recs[m] for m in models]),
            'panel_size': k,
            'gold_status': 'llm_panel_consensus_needs_human_signoff',
        }
        consensus_records.append(rec)
        if decision in ('verified', 'verified_with_correction'):
            verified.append(rec)
        elif decision == 'quarantine':
            quarantine.append(rec)
        else:
            rejected.append(rec)

    # ---- 统计 ----
    kappa5 = fleiss_kappa(rows5)
    kappa2 = fleiss_kappa(rows2)
    pair_kappa = {f'{m1}|{m2}': cohen_kappa([x for x, _ in v], [y for _, y in v])
                  for (m1, m2), v in pairwise.items()}
    n_total = len(consensus_records)
    dec_counts = Counter(r['panel_decision'] for r in consensus_records)
    ver_rate, ver_lo, ver_hi = wilson_ci(len(verified), n_total)
    per_model_stats = {
        m: {'supported': per_model_supported[m], 'total': per_model_total[m],
            'support_rate': round(per_model_supported[m] / per_model_total[m], 4) if per_model_total[m] else None}
        for m in models}
    per_pred = defaultdict(Counter)
    for r in consensus_records:
        per_pred[r['predicate']][r['panel_decision']] += 1
    label_dist = Counter(r['consensus_label'] for r in consensus_records)

    summary = {
        'models': models, 'panel_size': k,
        'facts_total': len(facts), 'facts_adjudicated': n_total, 'facts_incomplete': len(incomplete),
        'panel_decisions': dict(dec_counts),
        'verified_rate': round(ver_rate, 4), 'verified_rate_wilson95': [round(ver_lo, 4), round(ver_hi, 4)],
        'consensus_label_distribution': dict(label_dist),
        'fleiss_kappa_5class': round(kappa5, 4) if kappa5 is not None else None,
        'fleiss_kappa_binary': round(kappa2, 4) if kappa2 is not None else None,
        'pairwise_cohen_kappa': {kk: round(v, 4) for kk, v in pair_kappa.items() if v is not None},
        'per_model_stats': per_model_stats,
        'per_predicate_decisions': {p: dict(c) for p, c in per_pred.items()},
        'incomplete_fact_ids': [x['fact_id'] for x in incomplete][:50],
        'note': 'LLM panel consensus ≠ human expert gold；human_review_packet.csv 提供人工签核入口',
    }

    jdir = Path(a.jury)
    for name, data in [('consensus', consensus_records), ('verified_facts', verified),
                       ('quarantine_facts', quarantine), ('rejected_facts', rejected)]:
        with (jdir / (name + '.jsonl')).open('w', encoding='utf-8') as f:
            for x in data:
                f.write(json.dumps(x, ensure_ascii=False) + '\n')
    (jdir / 'agreement_summary.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding='utf-8')

    # ---- 人工签核包：quarantine 全量 + verified/rejected 分层抽样 ----
    def strat_sample(records, n):
        by_pred = defaultdict(list)
        for r in records:
            by_pred[r['predicate']].append(r)
        picked = []
        while len(picked) < n and any(by_pred.values()):
            for p in list(by_pred):
                if by_pred[p] and len(picked) < n:
                    picked.append(by_pred[p].pop(0))
        return picked

    packet = list(quarantine) + strat_sample(verified, 15) + strat_sample(rejected, 10)
    with (jdir / 'human_review_packet.csv').open('w', encoding='utf-8', newline='') as f:
        w = csv.writer(f)
        w.writerow(['fact_id', 'subject', 'predicate', 'object', 'evidence_text', 'panel_votes',
                    'consensus_label', 'panel_decision', 'priority',
                    'human_label', 'human_corrected_subject', 'human_corrected_predicate',
                    'human_corrected_object', 'human_note', 'reviewer', 'date'])
        for r in packet:
            prio = 'P0' if r['panel_decision'] == 'quarantine' else ('P1' if r['panel_decision'].startswith('verified') else 'P2')
            w.writerow([r['fact_id'], r['subject_name'], r['predicate'], r['object_name'],
                        r['surface_text'], json.dumps(r['per_model_labels'], ensure_ascii=False),
                        r['consensus_label'], r['panel_decision'], prio, '', '', '', '', '', '', ''])

    # ---- 共识版 golden 基准（8:2, seed 2025）----
    gdir = Path(a.golden_out)
    gdir.mkdir(parents=True, exist_ok=True)
    pool = sorted(consensus_records, key=lambda r: r['fact_id'])
    random.Random(a.seed).shuffle(pool)
    n_test = max(1, round(len(pool) * 0.2)) if pool else 0
    test, train = pool[:n_test], pool[n_test:]
    for name, data in [('gold_test', test), ('train_reference', train), ('gold_reference', pool)]:
        with (gdir / (name + '.jsonl')).open('w', encoding='utf-8') as f:
            for r in data:
                f.write(json.dumps(r, ensure_ascii=False) + '\n')
    (gdir / 'summary.json').write_text(json.dumps(
        {'seed': a.seed, 'total': len(pool), 'test': len(test), 'train': len(train),
         'test_label_distribution': dict(Counter(r['consensus_label'] for r in test)),
         'gold_status': 'llm_panel_consensus_needs_human_signoff'}, ensure_ascii=False, indent=2), encoding='utf-8')

    print(json.dumps({kk: vv for kk, vv in summary.items() if kk != 'incomplete_fact_ids'},
                     ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
