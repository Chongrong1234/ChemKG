#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""strict_extract_v2.py — 电镀领域严格证据优先抽取器 v2.

相对 v1 (strict_extract.py) 的修复（编号对应评审意见 P0）：
 F1  添加剂缩写大小写敏感 + 单位上下文守卫 —— 根治 mg(单位)/MG(孔雀石绿)/Mg(镁) 被折叠为
     同一实体的问题（v1 中幽灵实体 "mg" 卷入 61/119 条关系）。
 F2  别名表实现确定性实体融合（孔雀石绿→MG、氯化硝基四氮唑蓝→NBT、copper sulfate→CuSO4 等）。
 F3  主体与客体都必须出现在同一子句内（v1 的客体可从整行任意位置取，产生跨句错绑）。
 F4  谓词判定顺序改为 synergizes → improves_filling → inhibits → accelerates → used_as_* → adsorbs_on，
     修复 "enhance the filling performance" 被 accelerates_deposition 抢占的错判；
     并将 enhance 从 accelerates 触发词中移除。
 F5  实验条件槽（浓度/温度/电流密度/电位/pH/时间/转速/几何/阻抗/百分比）逐条绑定到事实，
     子句优先、整行回退并标注 scope，条件不再是悬空数值。
 F6  子句切分支持中文（v1 要求标点后必须有空格，中文段落从不切分）。
 F7  扩展单位集（mol/L、mmol/L、ppm、mA/cm²、A/m²、℃、s、Ω、mg L<sup>-1</sup> 归一化、数值范围、pH）。
 F8  扩展实体类型：Via / Electrolyte / Substrate / Metal / Mechanism / Method(扩充) / Role / Surface。
 F9  扩展谓词：used_as_leveler / used_as_suppressor / used_as_accelerator / used_as_inhibitor、adsorbs_on。
 F10 主体选择 = 距谓词触发词最近的化学/添加剂实体（v1 取第一个）。

所有结果仍为 candidate，最终裁决交给五模型评审团 + 人工签核。
"""
from __future__ import annotations
import argparse, json, re, hashlib
from pathlib import Path
from collections import Counter, defaultdict

# ---------------- 领域门控 ----------------
DOMAIN = re.compile(r"electroplating|electrodeposition|electro-deposition|plating bath|copper plating|cobalt plating|micro.?via|blind.?via|through.?hole|via fill|via filling|填充|电镀|电沉积|通孔|盲孔|镀铜|镀钴|镀液|镀层", re.I)
STRONG = re.compile(r"electropl|electrodepos|via fill|micro.?via|blind.?via|through.?hole|电镀|电沉积|镀铜|镀钴|超填充|填充", re.I)
NON_DOMAIN = re.compile(r"catalys|cross.?coupling|nanocatal|photocatal|cvd|chemical vapor deposition|cmp|chemical mechanical polishing|microwave absorption|organic transformation|腐蚀|催化", re.I)
REF = re.compile(r"doi\s*:|doi\.org|https?://|references?$|^\s*\[?\d{1,3}\]?\s+[^ ]+\s+et al\.?", re.I)

# ---------------- 实体模式 ----------------
ACRO = r"Cz-BPDB|AN-S1|PUB2|TPM|CMHT|PEP|SPS|JGB|PVP|PEG|DMG|ZPS|MPS|NBT|VMS|CDT|AB1|ADO|MG|DB|SA"
# 大小写敏感编译的缩写模式（防 mg/MG/Mg、co/Co、cv/CV 混淆）；完整词模式带 re.I。
PATTERNS = [
    ('Additive', re.compile(r"(?<![A-Za-z0-9-])(?:" + ACRO + r")(?![A-Za-z0-9/])(?!\s*/\s*L)")),
    ('Additive', re.compile(r"孔雀石绿|氯化硝基四氮唑蓝|聚乙烯吡咯烷酮|糖精")),
    ('Metal', re.compile(r"\b(?:Cu|Co|Ni)\b")),
    ('Method', re.compile(r"\b(?:CV|EIS|GM|XRD|SEM|XPS|EQCM)\b")),
    ('Via', re.compile(r"\bTH\b")),
    ('Property', re.compile(r"\bFR\b")),
    ('Chemical', re.compile(r"(?:Cl|I|Br)\s*[-−](?![A-Za-z0-9/])")),
    ('Chemical', re.compile(r"(?:Cl\s*(?:<sup>\s*[-−]\s*</sup>|\^\s*[-−]|\^\s*\{\s*[-−]\s*\}|<sup>\s*2\s*\+\s*</sup>)|Cu\s*(?:<sup>\s*2\s*\+\s*</sup>|\^\s*2\s*\+|\^\s*\{\s*2\s*\+\s*\})|Co\s*(?:<sup>\s*2\s*\+\s*</sup>|\^\s*2\s*\+|\^\s*\{\s*2\s*\+\s*\}))", re.I)),
    ('Chemical', re.compile(r"\$\\mathrm\s*\{?\s*C\s*[ul]\s*\^\s*\{?\s*[-−2+]\s*\}?\s*\}\s*\$", re.I)),
    ('Chemical', re.compile(r"\$\\mathrm\s*\{?\s*[CI]\s*\^\s*\{\s*[-−]\s*\}\s*\}?\s*\$", re.I)),
    ('Chemical', re.compile(r"\b(?:CuSO4(?:·5H2O)?|CoSO4|H2SO4|H3BO3|NaCl|Cu\(II\)|Co\(II\)|chloride|iodide|sulfuric acid|copper sulfate|boric acid|硫酸铜|硫酸|氯离子|硼酸|氯化钠)\b", re.I)),
    ('Method', re.compile(r"\b(?:chronoamperometry|cyclic voltammetry|electrochemical impedance spectroscopy|Raman)\b|循环伏安|电化学阻抗|计时安培|拉曼", re.I)),
    ('Process', re.compile(r"\b(?:(?:copper|cobalt)\s+(?:electroplating|electrodeposition)|electroplating|electrodeposition|superconformal|bottom.?up)\b|电镀|电沉积|超共形|超填充|自底向上|镀铜|镀钴|镀镍|镀层", re.I)),
    ('Via', re.compile(r"\b(?:micro.?via|blind.?via|through.?hole|trench)\b|通孔|盲孔|微盲孔|沟槽", re.I)),
    ('Property', re.compile(r"\b(?:filling performance|filling rate|surface copper|overpotential|polarization|deposition rate|throwing power|hardness|conductivity|void|seam)\b|填充性能|填充率|表面铜|过电位|极化|沉积速率|空洞|接缝|硬度|导电性", re.I)),
    ('Electrolyte', re.compile(r"\b(?:electrolyte|plating bath|bath)\b|镀液|电解液", re.I)),
    ('Substrate', re.compile(r"\b(?:PCB|wafer|substrate)\b|晶圆|基板|铜基底", re.I)),
    ('Mechanism', re.compile(r"\b(?:adsorption|nucleation|mass.?transfer|diffusion|passivation)\b|吸附|成核|传质|扩散|钝化", re.I)),
]

# 确定性别名表（surface.casefold() → 规范名）
ALIAS_CI = {k.casefold(): v for k, v in {
    '孔雀石绿': 'MG', 'malachite green': 'MG',
    '氯化硝基四氮唑蓝': 'NBT', 'nitro blue tetrazolium': 'NBT',
    '聚乙烯吡咯烷酮': 'PVP', 'polyvinylpyrrolidone': 'PVP',
    '糖精': 'saccharin', 'saccharin': 'saccharin',
    '硫酸铜': 'CuSO4', 'copper sulfate': 'CuSO4',
    '硫酸': 'H2SO4', 'sulfuric acid': 'H2SO4',
    '硼酸': 'H3BO3', 'boric acid': 'H3BO3',
    '氯化钠': 'NaCl', '氯离子': 'Cl-', 'chloride': 'Cl-',
}.items()}

SUBJ_TYPES = {'Additive', 'Chemical'}
OBJ_TYPES = {'Process', 'Property', 'Via', 'Metal', 'Electrolyte', 'Mechanism', 'Chemical', 'Additive', 'Substrate'}

ROLE_ENTITIES = {r: {'entity_id': 'ent_' + hashlib.sha1(('Role:' + r).encode()).hexdigest()[:16],
                     'name': r, 'type': 'Role'} for r in ('leveler', 'suppressor', 'accelerator', 'inhibitor')}
SURFACE_ENTITY = {'entity_id': 'ent_' + hashlib.sha1('Surface:electrode surface'.encode()).hexdigest()[:16],
                  'name': 'electrode surface', 'type': 'Surface'}

# ---------------- 谓词触发词 ----------------
SYNERGY = re.compile(r"\b(?:synerg\w+|work\w*\s+synergistically|cooperat\w+\s+effect)\b|协同", re.I)
IMPROVE = re.compile(r"\b(?:improv\w+|enhanc\w+|excellent|void.?free|seamless|superconformal|superfill\w*)\b|改善|提高|优异|无空洞|无缝隙|超共形|超填充|实现[^。；，,]{0,20}(?:填充|无缝)", re.I)
FILLCTX = re.compile(r"\b(?:fill\w*|hole|micro.?via|through.?hole|blind.?via|trench|void)\b|填充|通孔|盲孔|微盲孔|孔|缝隙", re.I)
INHIBIT = re.compile(r"\b(?:inhibits?|inhibited|inhibiting|suppresses?|suppressed|suppressing|retard\w*)\b|抑制(?!剂)|阻碍|阻滞", re.I)
ACCEL = re.compile(r"\b(?:accelerat\w+|promot\w+|catalyz\w+)\b|加速(?!剂)|促进(?!剂)", re.I)
DEPCTX = re.compile(r"\b(?:deposit\w*|plating|electroplating|electrodeposition|nucleat\w*)\b|沉积|电镀|镀铜|镀钴|镀镍|镀层", re.I)
HERCTX = re.compile(r"\b(?:hydrogen evolution|HER)\b|析氢|氢还原|氢析出", re.I)
ADSORB = re.compile(r"\b(?:adsorb\w*|adsorption)\b|吸附", re.I)
SURFCTX = re.compile(r"\b(?:surface|cathode|anode|electrode)\b|阴极|表面|电极", re.I)
ROLE_RE = re.compile(
    r"(?:作为|用[作当]|充当|是)[^。；，,]{0,12}?(整平剂|抑制剂|加速剂|促进剂|表面活性剂)"
    r"|(?:\bas\b|\bis\b|\bare\b|\bserves?\b|\bacts?\b|\bused?\b)[^.;,]{0,30}?\b(level(?:l)?ers?|suppress\w*|accelerat\w*|inhibitors?)\b", re.I)
ROLE_CN = {'整平剂': 'leveler', '抑制剂': 'inhibitor', '加速剂': 'accelerator', '促进剂': 'accelerator', '表面活性剂': None}
ROLE_EN = lambda w: ('leveler' if w.lower().startswith('level') else
                     'suppressor' if w.lower().startswith('suppress') else
                     'accelerator' if w.lower().startswith('accelerat') else
                     'inhibitor' if w.lower().startswith('inhibitor') else None)

# ---------------- 数值 / 单位 / pH ----------------
SAFE_UNIT = (r"(?:mmol\s*/\s*L|μmol\s*/\s*L|umol\s*/\s*L|mol\s*/\s*L|mg\s*/\s*L|μg\s*/\s*L|ug\s*/\s*L|ng\s*/\s*L|g\s*/\s*L"
             r"|ppm|ppb"
             r"|mA\s*/\s*cm\s*\^?2|mA\s*/\s*cm²|A\s*/\s*dm\s*\^?2|A\s*/\s*dm²|A\s*/\s*cm\s*\^?2|A\s*/\s*cm²|A\s*/\s*m\s*\^?2|A\s*/\s*m²"
             r"|rpm|mV|°\s*C|°C|℃|%|Ω\s*cm\s*\^?2|Ω\s*cm²|Ω)")
AMB_UNIT = r"(?:V|K|μm|µm|um|nm|mm|cm|min(?:ute)?s?|h(?:ours?)?|s(?:econds?)?)(?![A-Za-z])"
NUM = re.compile(r"(?<![A-Za-z0-9])(?P<value>[−-]?\d+(?:\.\d+)?)(?:\s*[~～–—-]\s*(?P<value2>\d+(?:\.\d+)?))?\s*(?:(?P<safe>" + SAFE_UNIT + r")|(?P<amb>" + AMB_UNIT + r"))", re.I)
PH = re.compile(r"\bpH\s*(?:值|value)?\s*[=约为是:：]?\s*(?P<value>\d+(?:\.\d+)?)", re.I)
SLOT = {'mg/L': 'concentration', 'g/L': 'concentration', 'mmol/L': 'concentration', 'mol/L': 'concentration',
        'μmol/L': 'concentration', 'μg/L': 'concentration', 'ng/L': 'concentration', 'ppm': 'concentration', 'ppb': 'concentration',
        'K': 'temperature', '°C': 'temperature', '℃': 'temperature',
        'A/dm²': 'current_density', 'A/cm²': 'current_density', 'mA/cm²': 'current_density', 'A/m²': 'current_density',
        'V': 'potential', 'mV': 'potential', 'h': 'time', 'min': 'time', 's': 'time',
        'μm': 'geometry', 'nm': 'geometry', 'mm': 'geometry', 'cm': 'geometry',
        'rpm': 'rotation', '%': 'percentage', 'Ω': 'impedance', 'Ω·cm²': 'impedance'}
UNIT_MAP = {'mg/l': 'mg/L', 'g/l': 'g/L', 'mmol/l': 'mmol/L', 'mol/l': 'mol/L', 'μmol/l': 'μmol/L', 'umol/l': 'μmol/L',
            'μg/l': 'μg/L', 'ug/l': 'μg/L', 'ng/l': 'ng/L', 'ppm': 'ppm', 'ppb': 'ppb',
            'ma/cm2': 'mA/cm²', 'a/dm2': 'A/dm²', 'a/cm2': 'A/cm²', 'a/m2': 'A/m²',
            'mv': 'mV', 'v': 'V', 'k': 'K', '°c': '°C', '℃': '°C',
            'μm': 'μm', 'µm': 'μm', 'um': 'μm', 'nm': 'nm', 'mm': 'mm', 'cm': 'cm',
            'rpm': 'rpm', 'min': 'min', 'minutes': 'min', 'h': 'h', 'hours': 'h', 's': 's', 'seconds': 's',
            '%': '%', 'ω': 'Ω', 'ωcm2': 'Ω·cm²', 'ω·cm2': 'Ω·cm²', 'ωcm²': 'Ω·cm²', 'ocm2': 'Ω·cm²'}

CLAUSE_SEP = re.compile(r"[。！？；;]|(?<=[.!?])\s+|(?<=,)\s+")


def hid(x: str) -> str:
    return hashlib.sha1(x.encode('utf-8', 'ignore')).hexdigest()[:16]


def unit_norm(u: str) -> str:
    u = re.sub(r'\s+', '', u).replace('µ', 'μ').replace('²', '2').lower()
    return UNIT_MAP.get(u, u)


def preprocess(line: str) -> str:
    # "mg L<sup>-1</sup>" → "mg/L"（仅处理跟在 L 后的上标 -1，不影响 cm<sup>-1</sup> 拉曼峰）
    line = re.sub(r'L\s*<sup>\s*[-−]?\s*1\s*</sup>\s*', '/L', line)
    line = re.sub(r'L\s*\^\s*[-−]\s*1\b', '/L', line)
    # 带空格的 LaTeX 离子形式 "$\mathrm { C l ^ { - } }$" → "Cl-"
    line = re.sub(r'\$\\mathrm\s*\{?\s*C\s*([ul])\s*\^\s*\{?\s*([-−+])\s*\}?\s*\}?\s*\$',
                  lambda m: 'Cl' + m.group(2).replace('−', '-'), line)
    return line


def clause_spans(line: str):
    spans, prev = [], 0
    for m in CLAUSE_SEP.finditer(line):
        cut = m.start() if m.group(0)[0].isspace() else m.end()
        if line[prev:cut].strip():
            spans.append((prev, cut))
        prev = cut
    if line[prev:].strip():
        spans.append((prev, len(line)))
    return spans


def extract_conditions(text: str, scope: str):
    out = []
    for m in NUM.finditer(text):
        raw_unit = m.group('safe') or m.group('amb')
        u = unit_norm(raw_unit or '')
        slot = SLOT.get(u)
        if not slot:
            continue
        rec = {'slot': slot, 'value': m.group('value').replace('−', '-'), 'unit': u,
               'raw': m.group(0).strip(), 'scope': scope}
        if m.group('value2'):
            rec['value2'] = m.group('value2').replace('−', '-')
        out.append(rec)
    for m in PH.finditer(text):
        out.append({'slot': 'pH', 'value': m.group('value'), 'unit': 'pH', 'raw': m.group(0).strip(), 'scope': scope})
    return out


def nearest(cands, pos):
    """cands: [(ent, positions)] → 距 pos 最近的实体"""
    best, bd = None, 10 ** 9
    for e, ps in cands:
        for p in ps:
            if abs(p - pos) < bd:
                bd, best = abs(p - pos), e
    return best


def resolve_predicates(c, hits):
    """hits: [(ent_dict, [clause内位置])]。返回 [(pred, subj_ent, obj_ent, trigger_match)]"""
    chem = [(e, ps) for e, ps in hits if e['type'] in SUBJ_TYPES]
    results = []

    def objs_excl(subj):
        return [(e, ps) for e, ps in hits if e['type'] in OBJ_TYPES and (subj is None or e['entity_id'] != subj['entity_id'])]

    m = SYNERGY.search(c)
    if m and len(chem) >= 2:
        s = nearest(chem, m.start())
        o = nearest([x for x in chem if x[0]['entity_id'] != s['entity_id']], m.start())
        if s and o:
            results.append(('synergizes_with', s, o, m))
            return results

    m = IMPROVE.search(c)
    if m and FILLCTX.search(c):
        s = nearest(chem, m.start())
        o = nearest(objs_excl(s), m.start())
        if s and o:
            results.append(('improves_filling', s, o, m))
            return results

    m = INHIBIT.search(c)
    if m and DEPCTX.search(c):
        s = nearest(chem, m.start())
        o = nearest(objs_excl(s), m.start())
        if s and o:
            results.append(('inhibits_deposition', s, o, m))
            return results

    m = ACCEL.search(c)
    if m and DEPCTX.search(c) and not (HERCTX.search(c) and not re.search(r'沉积|deposition|deposit\b', c, re.I)):
        s = nearest(chem, m.start())
        o = nearest(objs_excl(s), m.start())
        if s and o:
            results.append(('accelerates_deposition', s, o, m))
            return results

    m = ROLE_RE.search(c)
    if m:
        role = ROLE_CN.get(m.group(1)) if m.group(1) else ROLE_EN(m.group(2) or '')
        if role:
            s = nearest(chem, m.start())
            if s:
                results.append(('used_as_' + role, s, ROLE_ENTITIES[role], m))
                return results

    m = ADSORB.search(c)
    if m:
        s = nearest(chem, m.start())
        tgt = [(e, ps) for e, ps in hits if e['type'] in ('Metal', 'Substrate')]
        o = nearest(tgt, m.start()) if tgt else (SURFACE_ENTITY if SURFCTX.search(c) else None)
        if s and o:
            results.append(('adsorbs_on', s, o, m))
            return results
    return results


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--input', default='文献提取')
    ap.add_argument('--out', default='strict_extraction_v2')
    a = ap.parse_args()
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)

    docs, evs, ents, mentions, vals, rels, conds = [], [], [], [], [], [], []
    ent_index = {}          # entity_id -> record
    extra_entities = {}     # Role/Surface 概念实体

    for p in sorted(Path(a.input).rglob('full.md')):
        text = p.read_text(encoding='utf-8', errors='ignore')
        did = 'doc_' + hid(str(p.resolve()))
        docs.append({'doc_id': did, 'path': str(p),
                     'title': next((x[2:].strip() for x in text.splitlines() if x.startswith('# ')), p.parent.name)})
        ref = False
        for ln, raw_line in enumerate(text.splitlines(), 1):
            if re.match(r'^#{1,3}\s*(references|参考文献)', raw_line, re.I):
                ref = True
            if ref or len(raw_line.strip()) < 20 or not DOMAIN.search(raw_line) \
               or (NON_DOMAIN.search(raw_line) and not STRONG.search(raw_line)) or REF.search(raw_line):
                continue
            line = preprocess(raw_line)
            eid = 'ev_' + hid(f'{did}:{ln}:{raw_line}')
            evs.append({'evidence_id': eid, 'doc_id': did, 'line_no': ln, 'text': raw_line[:4000], 'review_status': 'unreviewed'})

            # --- 实体检测（行级，带位置） ---
            ent_positions = defaultdict(list)   # entity_id -> [start]
            ent_forms = defaultdict(set)        # entity_id -> {surface}
            for typ, pat in PATTERNS:
                for mt in pat.finditer(line):
                    surface = mt.group(0).strip()
                    canon = ALIAS_CI.get(surface.casefold(), surface).replace('−', '-').strip()
                    key = typ + ':' + canon.casefold()
                    ent_id = 'ent_' + hid(key)
                    if ent_id not in ent_index:
                        ent_index[ent_id] = {'entity_id': ent_id, 'key': key, 'type': typ, 'canon': canon}
                    ent_positions[ent_id].append(mt.start())
                    ent_forms[ent_id].add(surface)

            line_ents = []
            for ent_id in ent_positions:
                rec = ent_index[ent_id]
                forms = sorted(ent_forms[ent_id])
                e = {'entity_id': ent_id, 'name': rec['canon'], 'type': rec['type'], 'canon': rec['canon'], 'forms': forms}
                line_ents.append(e)
                if ent_id not in {x['entity_id'] for x in ents}:
                    ents.append({'entity_id': ent_id, 'name': rec['canon'], 'type': rec['type'],
                                 'normalized_name': rec['canon'].casefold(), 'surface_forms': forms, 'status': 'candidate'})
                mentions.append({'mention_id': 'men_' + hid(eid + ent_id), 'entity_id': ent_id,
                                 'evidence_id': eid, 'doc_id': did, 'text': forms[0], 'line_no': ln})

            # --- 数值（行级，全局 values.jsonl） ---
            for m in NUM.finditer(line):
                u = unit_norm(m.group('safe') or m.group('amb') or '')
                slot = SLOT.get(u)
                if not slot:
                    continue
                v = {'value_id': 'val_' + hid(eid + m.group(0)), 'evidence_id': eid, 'doc_id': did,
                     'value': m.group('value').replace('−', '-'), 'unit': u, 'slot': slot,
                     'raw_text': m.group(0).strip(), 'status': 'candidate'}
                if m.group('value2'):
                    v['value2'] = m.group('value2').replace('−', '-')
                vals.append(v)

            # --- 子句级关系 + 条件绑定 ---
            for (ca, cb) in clause_spans(line):
                c = line[ca:cb]
                if len(c.strip()) < 8 or not DOMAIN.search(c) or NON_DOMAIN.search(c):
                    continue
                hits = []
                for e in line_ents:
                    ps = [p - ca for p in ent_positions[e['entity_id']] if ca <= p < cb]
                    if ps:
                        hits.append((e, ps))
                if not any(e['type'] in SUBJ_TYPES for e, _ in hits):
                    continue
                for pred, s, o, trig in resolve_predicates(c, hits):
                    fact_id = 'fact_' + hid(eid + pred + s['entity_id'] + o['entity_id'])
                    clause_conds = extract_conditions(c, 'clause')
                    line_conds = extract_conditions(line, 'line')
                    have = {x['slot'] for x in clause_conds}
                    merged = clause_conds + [x for x in line_conds if x['slot'] not in have]
                    rel = {'fact_id': fact_id, 'subject_id': s['entity_id'], 'subject_name': s['name'],
                           'predicate': pred, 'object_id': o['entity_id'], 'object_name': o['name'],
                           'evidence_id': eid, 'doc_id': did, 'line_no': ln,
                           'surface_text': c[:2000], 'conditions': merged,
                           'status': 'candidate', 'needs_review': True, 'extractor': 'strict_v2'}
                    rels.append(rel)
                    for cd in merged:
                        conds.append({'cond_id': 'cond_' + hid(fact_id + cd['slot'] + cd['raw']),
                                      'fact_id': fact_id, **cd, 'evidence_id': eid, 'doc_id': did})
                    for ent in (s, o):
                        if ent['entity_id'] not in {x['entity_id'] for x in ents} and ent['entity_id'] not in {x['entity_id'] for x in ents}:
                            extra_entities.setdefault(ent['entity_id'], {'entity_id': ent['entity_id'], 'name': ent.get('name'),
                                                                          'type': ent['type'], 'normalized_name': str(ent.get('name')).casefold(),
                                                                          'surface_forms': [ent.get('name')], 'status': 'concept'})

    for rec in extra_entities.values():
        ents.append(rec)

    # 去重
    ents = list({x['entity_id']: x for x in ents}.values())
    vals = list({x['value_id']: x for x in vals}.values())
    rels = list({x['fact_id']: x for x in rels}.values())
    conds = list({x['cond_id']: x for x in conds}.values())

    for n, data in [('documents', docs), ('evidence', evs), ('entities', ents), ('mentions', mentions),
                    ('values', vals), ('relations', rels), ('conditions', conds)]:
        with (out / (n + '.jsonl')).open('w', encoding='utf-8') as f:
            for x in data:
                f.write(json.dumps(x, ensure_ascii=False) + '\n')

    mg_ghost = sum(1 for r in rels if r['subject_name'] == 'mg' or r['object_name'] == 'mg')
    with_c = sum(1 for r in rels if r['conditions'])
    slot_dist = Counter(cd['slot'] for cd in conds)
    unit_dist = Counter(cd['unit'] for cd in conds)
    try:
        v1 = json.loads(Path('strict_extraction/summary.json').read_text(encoding='utf-8'))
    except Exception:
        v1 = None
    summary = {
        'documents': len(docs), 'evidence': len(evs), 'entities': len(ents), 'mentions': len(mentions),
        'values': len(vals), 'relations': len(rels), 'conditions': len(conds),
        'relation_types': dict(Counter(r['predicate'] for r in rels)),
        'entity_types': dict(Counter(e['type'] for e in ents)),
        'facts_with_conditions': with_c, 'condition_coverage': round(with_c / len(rels), 4) if rels else 0,
        'condition_slots': dict(slot_dist), 'unit_top10': dict(unit_dist.most_common(10)),
        'mg_ghost_facts': mg_ghost, 'llm_enabled': False, 'extractor': 'strict_v2',
        'comparison_v1': v1,
        'fixes': ['F1 mg/MG/Mg 大小写敏感+单位守卫', 'F2 别名实体融合', 'F3 子句内客体绑定',
                  'F4 谓词顺序修复', 'F5 条件槽绑定', 'F6 中文子句切分', 'F7 单位/pH/范围扩展',
                  'F8 实体类型扩展', 'F9 谓词扩展', 'F10 最近主体选择'],
    }
    (out / 'summary.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
