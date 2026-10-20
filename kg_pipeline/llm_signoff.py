#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""llm_signoff.py — 用评审团之外的大模型对人工签核包做"预标注"（dry run）。

目的：在真正人工签核前，先用 2 个独立于评审团的大模型（盲标，不告知评审团任何结论，
避免锚定）把签核包标一遍，跑通 jury_consistency.py 全流程并得到初步数字。

诚实声明：这是 LLM 预标注（pseudo-annotation），不是人工金标准。
标注员与评审团为同族不同版本模型（路由上 gpt/claude 当前不可用），独立性弱于
跨厂商标注；本结果用于流程验证与量级参考，最终论文数字仍需真人签核。

输出：
  jury/llm_signoff__<model>.jsonl     每个标注员的逐条判定
  jury/llm_signoff_iaa.json           两标注员一致性（模拟双人 IAA）
  jury/human_review_packet.csv        human_* 列填入主标注员结果（reviewer 注明 LLM 预标注）
"""
from __future__ import annotations
import argparse, csv, json, os, re, threading, time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from collections import Counter
import requests

PRIMARY = 'deepseek-v4-pro-preview'
SECONDARY = 'kimi-k2.7-code'

SYSTEM = """你是铜/钴电沉积、电镀添加剂与PCB通孔/盲孔填充领域的资深研究员，正在为知识图谱构建金标准做独立标注。只依据给出的证据文本独立判断，禁止使用证据外的常识补写，也不要猜测其他人可能给出的结论。

五分类标签：
- supported：证据明确支持该三元组（主体、客体、关系类型、方向均正确）。
- partial：大体支持但有瑕疵（如客体粒度过粗、条件表述不足）。
- unsupported：证据不支持（主体错误、客体错误、关系类型错误、方向错误、证据谈的是别的事物）。
- contradicted：证据明确否定该三元组。
- ambiguous：证据表述含糊，无法判定。

谓词定义（严格执行）：
- inhibits_deposition：抑制金属(Cu/Co/Ni)电沉积本身。促进析氢、缓蚀、抑制水解不算。
- accelerates_deposition：加速金属电沉积本身。加速析氢(HER)、加速腐蚀不算。
- improves_filling：改善孔/通孔/盲孔/沟槽的填充（填充率、无缝、无空洞、超共形）。硬度、附着力、光亮度不算。
- synergizes_with：两种及以上添加剂/化学组分之间的协同。
- used_as_leveler / used_as_suppressor / used_as_accelerator / used_as_inhibitor：该物质被用作整平剂/抑制剂/加速剂/缓蚀剂。
- adsorbs_on：该物质吸附于电极/金属/阴极/表面。

注意：MG=孔雀石绿(添加剂)；mg=毫克(单位，不是实体)。Cl⁻为氯离子。
若主体/客体/谓词有误，在corrected_*中给出修正。只输出一个JSON对象，不要Markdown。"""

SCHEMA = ('{"label":"supported|partial|unsupported|contradicted|ambiguous",'
          '"corrected_subject":null,"corrected_predicate":null,"corrected_object":null,'
          '"note":"简短中文说明"}')


def slug(m):
    return re.sub(r'[^A-Za-z0-9._-]+', '_', m)


def parse_json_loose(text):
    t = re.sub(r'^```(?:json)?\s*|\s*```$', '', (text or '').strip(), flags=re.S)
    try:
        return json.loads(t)
    except Exception:
        m = re.search(r'\{.*\}', t, re.S)
        if m:
            try:
                return json.loads(m.group(0))
            except Exception:
                return None
    return None


def call(row, model, base, key):
    prompt = (f"候选三元组（请独立标注是否被证据支持）\n"
              f"主体(subject): {row['subject']}\n"
              f"谓词(predicate): {row['predicate']}\n"
              f"客体(object): {row['object']}\n"
              f"证据文本: {row['evidence_text']}\n\n"
              f"严格输出符合以下结构的单个JSON对象：\n{SCHEMA}")
    use_fmt = True
    last_err = None
    for attempt in range(4):
        body = {'model': model, 'temperature': 0, 'max_tokens': 8000,
                'messages': [{'role': 'system', 'content': SYSTEM}, {'role': 'user', 'content': prompt}]}
        if use_fmt:
            body['response_format'] = {'type': 'json_object'}
        try:
            r = requests.post(base.rstrip('/') + '/chat/completions',
                              headers={'Authorization': 'Bearer ' + key, 'Content-Type': 'application/json'},
                              json=body, timeout=300)
            if r.status_code == 400 and use_fmt and 'response_format' in r.text[:800]:
                use_fmt = False
                continue
            r.raise_for_status()
            message = r.json()['choices'][0]['message']
            content = message.get('content') or message.get('reasoning_content') or ''
            obj = parse_json_loose(content)
            if obj is None:
                last_err = 'unparseable: ' + (content or '')[:200]
                continue
            obj.update({'fact_id': row['fact_id'], 'model': model})
            return obj
        except Exception as e:
            last_err = str(e)[:300]
            time.sleep(min(2 ** attempt * 2, 20))
    return {'fact_id': row['fact_id'], 'model': model, 'label': 'api_error',
            'corrected_subject': None, 'corrected_predicate': None, 'corrected_object': None,
            'note': 'API error: ' + str(last_err)}


def cohen_kappa(a, b):
    n = len(a)
    if n == 0:
        return None
    po = sum(1 for x, y in zip(a, b) if x == y) / n
    ca, cb = Counter(a), Counter(b)
    cats = sorted(set(a) | set(b))
    pe = sum((ca[c] / n) * (cb[c] / n) for c in cats)
    return (po - pe) / (1 - pe) if pe < 1 else 1.0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--packet', default='jury/human_review_packet.csv')
    ap.add_argument('--out', default='jury')
    ap.add_argument('--base-url', default=os.getenv('KG_LLM_BASE_URL', ''))
    ap.add_argument('--api-key', default=os.getenv('KG_LLM_API_KEY', ''))
    ap.add_argument('--primary', default=PRIMARY)
    ap.add_argument('--secondary', default=SECONDARY)
    ap.add_argument('--workers', type=int, default=6)
    a = ap.parse_args()
    if not (a.base_url and a.api_key):
        raise SystemExit('需要 --base-url / --api-key')

    with open(a.packet, encoding='utf-8', newline='') as f:
        rows = list(csv.DictReader(f))
    print(f'签核包: {len(rows)} 条；标注员: {a.primary}(主) + {a.secondary}(复核)', flush=True)

    out = Path(a.out)
    results = {m: {} for m in (a.primary, a.secondary)}

    tasks = []
    for m in (a.primary, a.secondary):
        f = out / ('llm_signoff__' + slug(m) + '.jsonl')
        done_ids = set()
        if f.exists():
            for line in f.read_text(encoding='utf-8').splitlines():
                if line.strip():
                    try:
                        rec = json.loads(line)
                        if rec.get('label') and rec['label'] != 'api_error':
                            results[m][rec['fact_id']] = rec
                            done_ids.add(rec['fact_id'])
                    except Exception:
                        pass
        for row in rows:
            if row['fact_id'] not in done_ids:
                tasks.append((m, row))
    print(f'待调用: {len(tasks)}', flush=True)

    locks = {m: threading.Lock() for m in results}
    files = {m: out / ('llm_signoff__' + slug(m) + '.jsonl') for m in results}

    if tasks:
        with ThreadPoolExecutor(max_workers=a.workers) as ex:
            futs = {ex.submit(call, row, m, a.base_url, a.api_key): (m, row['fact_id']) for m, row in tasks}
            n = 0
            for fut in as_completed(futs):
                m, fid = futs[fut]
                rec = fut.result()
                results[m][fid] = rec
                with locks[m]:
                    with files[m].open('a', encoding='utf-8') as fh:
                        fh.write(json.dumps(rec, ensure_ascii=False) + '\n')
                n += 1
                if n % 20 == 0:
                    print(f'progress {n}/{len(tasks)}', flush=True)

    # ---- 复核标注员 IAA（模拟双人标注一致性） ----
    common = [r['fact_id'] for r in rows
              if r['fact_id'] in results[a.primary] and r['fact_id'] in results[a.secondary]]
    la = [results[a.primary][fid].get('label') for fid in common]
    lb = [results[a.secondary][fid].get('label') for fid in common]
    valid = [(x, y) for x, y in zip(la, lb) if x != 'api_error' and y != 'api_error']
    va, vb = [x for x, _ in valid], [y for _, y in valid]
    exact = sum(1 for x, y in zip(va, vb) if x == y) / len(va) if va else None
    kappa = cohen_kappa(va, vb) if va else None
    acc = {'supported', 'partial'}
    ba = ['accepted' if x in acc else 'not_accepted' for x in va]
    bb = ['accepted' if y in acc else 'not_accepted' for y in vb]
    bexact = sum(1 for x, y in zip(ba, bb) if x == y) / len(ba) if ba else None
    iaa = {
        'annotator_primary': a.primary, 'annotator_secondary': a.secondary,
        'n_common': len(va),
        'exact_agreement_5class': round(exact, 4) if exact is not None else None,
        'cohen_kappa_5class': round(kappa, 4) if kappa is not None else None,
        'exact_agreement_binary': round(bexact, 4) if bexact is not None else None,
        'primary_label_dist': dict(Counter(va)), 'secondary_label_dist': dict(Counter(vb)),
        'disagreements': [
            {'fact_id': fid, 'primary': x, 'secondary': y,
             'subject': next((r['subject'] for r in rows if r['fact_id'] == fid), ''),
             'predicate': next((r['predicate'] for r in rows if r['fact_id'] == fid), ''),
             'object': next((r['object'] for r in rows if r['fact_id'] == fid), '')}
            for fid, x, y in zip(common, la, lb) if x != y and x != 'api_error' and y != 'api_error'],
        'note': 'LLM 双标注员模拟 IAA；两者与五模型评审团为同族不同版本，独立性有限。非人工金标准。',
    }
    (out / 'llm_signoff_iaa.json').write_text(json.dumps(iaa, ensure_ascii=False, indent=2), encoding='utf-8')

    # ---- 把主标注员结果填回签核包 ----
    today = time.strftime('%Y-%m-%d')
    filled = 0
    for row in rows:
        rec = results[a.primary].get(row['fact_id'])
        if rec and rec.get('label') and rec['label'] != 'api_error':
            row['human_label'] = rec['label']
            row['human_corrected_subject'] = rec.get('corrected_subject') or ''
            row['human_corrected_predicate'] = rec.get('corrected_predicate') or ''
            row['human_corrected_object'] = rec.get('corrected_object') or ''
            row['human_note'] = (rec.get('note') or '')[:500]
            row['reviewer'] = f'{a.primary} (LLM预标注,非人工)'
            row['date'] = today
            filled += 1

    with open(a.packet, 'w', encoding='utf-8', newline='') as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)

    print(f'\n主标注员完成 {filled}/{len(rows)} 条，已填回 {a.packet}')
    print(f'IAA(5类): exact={iaa["exact_agreement_5class"]} kappa={iaa["cohen_kappa_5class"]} '
          f'binary={iaa["exact_agreement_binary"]} n={len(va)}')
    print(f'分歧 {len(iaa["disagreements"])} 条 → jury/llm_signoff_iaa.json')


if __name__ == '__main__':
    main()
