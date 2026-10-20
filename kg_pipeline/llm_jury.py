#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""llm_jury.py — 多模型交叉验证评审团（checkpoint 断点续跑）。

修复 v1 审计协议的效度缺陷：v1 只送谓词+证据，模型自行重抽主客体，测得的是
"证据是否支持某类关系"，而非"管线三元组是否正确"。本版把管线抽取的
subject/predicate/object/conditions 一并送审，要求对三元组本身逐项裁决。

用法：
  python3 kg_pipeline/llm_jury.py \
      --input strict_extraction_v2/relations.jsonl --out jury \
      --base-url https://api.epicllmrouter.top/v1 --api-key $KEY \
      --models "m1,m2,m3,m4,m5" --workers 8
"""
from __future__ import annotations
import argparse, json, os, re, threading, time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from collections import Counter
import requests

SYSTEM = """你是铜/钴电沉积、电镀添加剂与PCB通孔/盲孔填充领域的资深文献标注专家，担任候选事实的独立裁决人。你的判定将用于构建知识图谱质量基准，必须严格、保守、可追溯。

判定规则：
1. 只依据给出的证据文本判断，禁止使用证据之外的领域常识补写。
2. 判定对象是"该三元组本身"：主体(subject)、谓词(predicate)、客体(object)是否同时正确、方向是否正确。
3. label 五分类：
   - supported：证据明确支持该三元组（主体、客体、关系类型、方向均正确）。
   - partial：大体支持但有瑕疵（如客体粒度过粗、条件不足导致关系强度存疑）。
   - unsupported：证据不支持该三元组（含主体错误、客体错误、关系类型错误、方向错误、证据谈的是别的事物）。
   - contradicted：证据明确否定该三元组。
   - ambiguous：证据表述含糊，无法判定。
4. 谓词语义定义（严格执行）：
   - inhibits_deposition：抑制金属(Cu/Co/Ni)的电沉积/电镀。促进析氢、缓蚀、吸附本身不等于抑制沉积。
   - accelerates_deposition：加速金属电沉积本身。加速析氢(HER)、加速腐蚀、降低电阻不算。
   - improves_filling：改善孔/通孔/盲孔/沟槽的填充(填充率、无缝、无空洞、超共形/底up)。硬度、附着力、光亮度不算。
   - synergizes_with：两种及以上添加剂/化学组分之间存在协同效应。
   - used_as_leveler / used_as_suppressor / used_as_accelerator / used_as_inhibitor：该物质被用作整平剂/抑制剂(缓聚)/加速剂/缓蚀剂。
   - adsorbs_on：该物质吸附于电极/金属/阴极/表面。
5. MG(孔雀石绿，添加剂)与 mg(毫克，单位，不是实体)不同；Co/Co2+是金属钴；按化学语义判断，忽略中英文差异。
6. conditions：从证据中抽取与该事实直接相关的实验条件(concentration/temperature/current_density/potential/pH/time/rotation/geometry)，每条含 slot/value/unit；无关条件不要抽；没有则为空数组。
7. 证据若属标题、图注、参考文献或跨领域(催化/CVD/CMP/腐蚀)，evidence_valid=false。
8. 只输出一个JSON对象，不要Markdown代码块，不要任何额外文字。"""

SCHEMA = ('{"label":"supported|partial|unsupported|contradicted|ambiguous",'
          '"subject_correct":true,"predicate_correct":true,"object_correct":true,'
          '"corrected_subject":null,"corrected_predicate":null,"corrected_object":null,'
          '"conditions":[{"slot":"concentration","value":"10","unit":"mg/L"}],'
          '"evidence_valid":true,"confidence":0.0,"reason":"简短中文理由"}')


def slug(model: str) -> str:
    return re.sub(r'[^A-Za-z0-9._-]+', '_', model)


def parse_json_loose(text: str):
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


def extract_content(message: dict):
    """兼容推理模型：content 为空时从 reasoning_content 提取 JSON。"""
    content = message.get('content')
    if content and content.strip():
        return content
    rc = message.get('reasoning_content') or message.get('reasoning') or ''
    if rc and rc.strip():
        return rc
    return content


def build_prompt(fact):
    cond = json.dumps(fact.get('conditions', []), ensure_ascii=False) if fact.get('conditions') else '[]'
    return (f"候选事实（请对该三元组本身作逐项裁决）\n"
            f"fact_id: {fact['fact_id']}\n"
            f"主体(subject): {fact.get('subject_name', '?')}\n"
            f"谓词(predicate): {fact['predicate']}\n"
            f"客体(object): {fact.get('object_name', '?')}\n"
            f"管线抽取的实验条件: {cond}\n"
            f"证据文本: {fact.get('surface_text', '')}\n\n"
            f"严格输出符合以下结构的单个JSON对象（不要Markdown、不要解释）：\n{SCHEMA}")


def call(fact, model, base, key, timeout=300):
    url = base.rstrip('/') + '/chat/completions'
    prompt = build_prompt(fact)
    use_fmt = True
    last_err = None
    for attempt in range(5):
        # 推理模型思维链可能很长：max_tokens 给足，避免 finish=length 且正文为空
        body = {'model': model, 'temperature': 0, 'max_tokens': 8000,
                'messages': [{'role': 'system', 'content': SYSTEM}, {'role': 'user', 'content': prompt}]}
        if use_fmt:
            body['response_format'] = {'type': 'json_object'}
        try:
            r = requests.post(url, headers={'Authorization': 'Bearer ' + key, 'Content-Type': 'application/json'},
                              json=body, timeout=timeout)
            if r.status_code == 400 and use_fmt and 'response_format' in r.text[:800]:
                use_fmt = False
                continue
            r.raise_for_status()
            message = r.json()['choices'][0]['message']
            content = extract_content(message)
            obj = parse_json_loose(content)
            if obj is None:
                last_err = 'unparseable: ' + (content or '')[:200]
                if attempt >= 3:
                    break
                continue
            obj.update({'fact_id': fact['fact_id'], 'evidence_id': fact.get('evidence_id'),
                        'original_predicate': fact['predicate'], 'original_subject': fact.get('subject_name'),
                        'original_object': fact.get('object_name'), 'surface_text': fact.get('surface_text', ''),
                        'model': model})
            return obj
        except Exception as e:
            last_err = str(e)[:300]
            time.sleep(min(2 ** attempt * 2, 30))
    return {'fact_id': fact['fact_id'], 'evidence_id': fact.get('evidence_id'),
            'original_predicate': fact['predicate'], 'original_subject': fact.get('subject_name'),
            'original_object': fact.get('object_name'), 'surface_text': fact.get('surface_text', ''),
            'label': 'api_error', 'domain_relevant': None, 'subject_correct': None, 'predicate_correct': None,
            'object_correct': None, 'corrected_subject': None, 'corrected_predicate': None,
            'corrected_object': None, 'conditions': [], 'evidence_valid': None, 'confidence': 0,
            'reason': 'API error: ' + str(last_err), 'model': model}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--input', default='strict_extraction_v2/relations.jsonl')
    ap.add_argument('--out', default='jury')
    ap.add_argument('--base-url', default=os.getenv('KG_LLM_BASE_URL', ''))
    ap.add_argument('--api-key', default=os.getenv('KG_LLM_API_KEY', ''))
    ap.add_argument('--models', default=os.getenv('KG_JURY_MODELS', ''))
    ap.add_argument('--workers', type=int, default=8)
    a = ap.parse_args()
    if not (a.base_url and a.api_key and a.models):
        raise SystemExit('需要 --base-url / --api-key / --models')

    models = [m.strip() for m in a.models.split(',') if m.strip()]
    facts = [json.loads(x) for x in Path(a.input).read_text(encoding='utf-8').splitlines() if x.strip()]
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    print(f'facts={len(facts)} models={len(models)} -> {a.out}', flush=True)

    # 断点续跑：每个模型独立记录已完成 fact_id；api_error 视为未完成（文件重写剔除）
    done = {}
    files = {}
    locks = {}
    for m in models:
        f = out / ('reviews__' + slug(m) + '.jsonl')
        files[m] = f
        locks[m] = threading.Lock()
        ids = set()
        if f.exists():
            valid_lines = []
            for line in f.read_text(encoding='utf-8').splitlines():
                if not line.strip():
                    continue
                try:
                    rec = json.loads(line)
                except Exception:
                    continue
                if rec.get('label') and rec.get('label') != 'api_error':
                    ids.add(rec['fact_id'])
                    valid_lines.append(line)
            if len(valid_lines) != sum(1 for l in f.read_text(encoding='utf-8').splitlines() if l.strip()):
                f.write_text('\n'.join(valid_lines) + ('\n' if valid_lines else ''), encoding='utf-8')
        done[m] = ids
        print(f'  {m}: 有效已完成 {len(ids)}', flush=True)

    tasks = [(m, fct) for m in models for fct in facts if fct['fact_id'] not in done[m]]
    print(f'待执行调用: {len(tasks)}', flush=True)
    if not tasks:
        print('全部完成。')
        return

    counter = {'n': 0}
    glock = threading.Lock()

    def write(m, rec):
        with locks[m]:
            with files[m].open('a', encoding='utf-8') as fh:
                fh.write(json.dumps(rec, ensure_ascii=False) + '\n')

    with ThreadPoolExecutor(max_workers=a.workers) as ex:
        futs = {ex.submit(call, fct, m, a.base_url, a.api_key): (m, fct['fact_id']) for m, fct in tasks}
        for fut in as_completed(futs):
            m, fid = futs[fut]
            try:
                rec = fut.result()
            except Exception as e:
                rec = {'fact_id': fid, 'label': 'api_error', 'model': m, 'reason': 'task error: ' + str(e)[:200]}
            write(m, rec)
            with glock:
                counter['n'] += 1
                if counter['n'] % 25 == 0:
                    print(f"progress {counter['n']}/{len(tasks)}", flush=True)

    for m in models:
        labels = Counter()
        for line in files[m].read_text(encoding='utf-8').splitlines():
            if line.strip():
                try:
                    labels[json.loads(line).get('label')] += 1
                except Exception:
                    pass
        print(f'{m}: {dict(labels)}', flush=True)


if __name__ == '__main__':
    main()
