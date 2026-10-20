#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""jury_consistency.py — 评审团共识与人工签核结果的一致性回填分析。

输入：
  jury/human_review_packet.csv 人工签核结果（human_label 列非空的行为已签核）
输出：
  jury/human_vs_panel.json       一致率、Cohen's κ、分歧明细、panel 决策的效度指标
  jury/golden_final.jsonl        以人工标签覆盖共识标签的最终 golden 集
（本脚本在人工签核完成后运行；当前 packet 全空时只输出占位报告。）
"""
from __future__ import annotations
import csv, json, math
from pathlib import Path
from collections import Counter


def wilson(k, n, z=1.96):
    if n == 0:
        return 0.0, 0.0, 0.0
    p = k / n
    d = 1 + z * z / n
    c = p + z * z / (2 * n)
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return p, max(0.0, (c - h) / d), min(1.0, (c + h) / d)


def cohen_kappa(a, b):
    n = len(a)
    po = sum(1 for x, y in zip(a, b) if x == y) / n
    ca, cb = Counter(a), Counter(b)
    cats = sorted(set(a) | set(b))
    pe = sum((ca[c] / n) * (cb[c] / n) for c in cats)
    return (po - pe) / (1 - pe) if pe < 1 else 1.0


def main():
    packet_path = Path('jury/human_review_packet.csv')
    consensus = {json.loads(l)['fact_id']: json.loads(l)
                 for l in Path('jury/consensus.jsonl').read_text(encoding='utf-8').splitlines() if l.strip()}
    rows = list(csv.DictReader(packet_path.open(encoding='utf-8')))
    signed = [r for r in rows if r.get('human_label')]
    print(f'签核行: {len(signed)}/{len(rows)}')

    if not signed:
        Path('jury/human_vs_panel.json').write_text(json.dumps(
            {'signed': 0, 'total_packet': len(rows),
             'note': '人工签核尚未开始。填好 human_review_packet.csv 的 human_label 列后重跑本脚本。'},
            ensure_ascii=False, indent=2), encoding='utf-8')
        print('尚未签核，已写占位报告。')
        return

    # 二分类映射：supported/partial → panel 视为接受
    acc = {'supported', 'partial'}
    h5, p5, h2, p2 = [], [], [], []
    mismatches = []
    for r in signed:
        fid = r['fact_id']
        con = consensus.get(fid)
        if not con:
            continue
        h5.append(r['human_label'])
        p5.append(con['consensus_label'])
        h2.append('accepted' if r['human_label'] in acc else 'not_accepted')
        p2.append('accepted' if con['consensus_label'] in acc else 'not_accepted')
        if r['human_label'] != con['consensus_label']:
            mismatches.append({'fact_id': fid, 'human': r['human_label'],
                               'panel': con['consensus_label'],
                               'panel_votes': con['per_model_labels'],
                               'subject': con['subject_name'], 'predicate': con['predicate'],
                               'object': con['object_name'], 'evidence': con['surface_text'][:300],
                               'human_note': r.get('human_note', '')})

    agree5 = sum(1 for x, y in zip(h5, p5) if x == y) / len(h5)
    agree2 = sum(1 for x, y in zip(h2, p2) if x == y) / len(h2)
    k5 = cohen_kappa(h5, p5)
    k2 = cohen_kappa(h2, p2)

    # 以人工标签为参照的 panel 决策效度
    dec_map = {'verified': 'accepted', 'verified_with_correction': 'accepted',
               'quarantine': 'not_accepted', 'rejected': 'not_accepted'}
    tp = fp = tn = fn = 0
    for r in signed:
        con = consensus.get(r['fact_id'])
        if not con:
            continue
        pd = dec_map.get(con['panel_decision'], 'not_accepted')
        hd = 'accepted' if r['human_label'] in acc else 'not_accepted'
        if pd == 'accepted' and hd == 'accepted':
            tp += 1
        elif pd == 'accepted':
            fp += 1
        elif hd == 'accepted':
            fn += 1
        else:
            tn += 1
    prec = tp / (tp + fp) if tp + fp else None
    rec = tp / (tp + fn) if tp + fn else None
    prec_ci = wilson(tp, tp + fp) if tp + fp else (None, None, None)

    out = {
        'signed': len(signed), 'packet_total': len(rows),
        'exact_agreement_5class': round(agree5, 4),
        'agreement_binary_accepted': round(agree2, 4),
        'cohen_kappa_5class': round(k5, 4), 'cohen_kappa_binary': round(k2, 4),
        'panel_vs_human_confusion': {'tp': tp, 'fp': fp, 'tn': tn, 'fn': fn},
        'panel_accept_precision_vs_human': round(prec, 4) if prec is not None else None,
        'panel_accept_precision_wilson95': [round(prec_ci[1], 4), round(prec_ci[2], 4)] if prec_ci[0] is not None else None,
        'panel_accept_recall_vs_human': round(rec, 4) if rec is not None else None,
        'mismatches': mismatches,
        'note': '人工标签为最终真值；panel 一致率用于刻画 LLM 评审团相对专家的可靠性。',
    }
    Path('jury/human_vs_panel.json').write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding='utf-8')

    # 最终 golden：人工标签覆盖（gold_status 按标注员身份如实标记）
    golden = []
    for r in signed:
        con = consensus.get(r['fact_id'])
        if not con:
            continue
        rec = dict(con)
        rec['human_label'] = r['human_label']
        rec['human_note'] = r.get('human_note', '')
        reviewer = r.get('reviewer', '') or ''
        rec['reviewer'] = reviewer
        rec['gold_status'] = ('llm_pre_annotated_pseudo_gold'
                              if 'LLM' in reviewer or 'llm' in reviewer or '预标注' in reviewer
                              else 'human_expert_signed')
        golden.append(rec)
    Path('jury/golden_final.jsonl').write_text(
        '\n'.join(json.dumps(x, ensure_ascii=False) for x in golden) + '\n', encoding='utf-8')

    print(json.dumps({k: v for k, v in out.items() if k != 'mismatches'}, ensure_ascii=False, indent=2))
    print(f'分歧 {len(mismatches)} 条已写入 jury/human_vs_panel.json；人工签核 golden {len(golden)} 条 → jury/golden_final.jsonl')


if __name__ == '__main__':
    main()
