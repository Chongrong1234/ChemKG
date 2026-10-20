#!/usr/bin/env python3
import argparse,csv,json,os,time
from concurrent.futures import ThreadPoolExecutor,as_completed
from pathlib import Path
import requests

SYSTEM='''你是电镀与电化学领域知识图谱审计专家。只根据给出的证据文本判断，不要补充证据外知识。目标领域：铜/钴电沉积、电镀、酸性铜/钴镀液、PCB通孔/盲孔/微盲孔填充及添加剂机理。催化、CVD、CMP、腐蚀、一般涂层、参考文献、标题或图注本身不能支持电镀事实。improves_filling必须有孔/通孔/盲孔/填充结果；synergizes_with必须明确两个化学物/添加剂和协同结果；关系方向必须与证据一致。条件（浓度、温度、电流密度、pH、时间、孔径/孔深）若缺失要指出。只输出JSON对象，不要Markdown。'''
SCHEMA='''{"label":"supported|partial|unsupported|contradicted|ambiguous","domain_relevant":true,"corrected_predicate":"same predicate or null","subject":"evidence中的主体或null","object":"evidence中的客体或null","conditions":["条件字符串"],"evidence_valid":true,"confidence":0.0,"reason":"简短中文理由"}'''

def call(row,base,key,model):
 prompt=f'''审核候选事实。原始谓词: {row['predicate']}\n证据: {row['surface_text']}\n严格输出符合此结构的JSON：{SCHEMA}'''
 body={'model':model,'temperature':0,'response_format':{'type':'json_object'},'messages':[{'role':'system','content':SYSTEM},{'role':'user','content':prompt}]}
 for attempt in range(3):
  try:
   r=requests.post(base.rstrip('/')+'/chat/completions',headers={'Authorization':'Bearer '+key,'Content-Type':'application/json'},json=body,timeout=120)
   r.raise_for_status(); content=r.json()['choices'][0]['message']['content']; obj=json.loads(content)
   obj.update({'fact_id':row['fact_id'],'evidence_id':row['evidence_id'],'original_predicate':row['predicate'],'surface_text':row['surface_text'],'model':model})
   return obj
  except Exception as e:
   if attempt==2: return {'fact_id':row['fact_id'],'evidence_id':row['evidence_id'],'original_predicate':row['predicate'],'label':'ambiguous','domain_relevant':None,'corrected_predicate':None,'subject':None,'object':None,'conditions':[],'evidence_valid':None,'confidence':0,'reason':'API error: '+str(e),'model':model}
   time.sleep(2**attempt)

def main():
 ap=argparse.ArgumentParser();ap.add_argument('--input',default='strict_extraction/relations.jsonl');ap.add_argument('--out',default='strict_extraction/llm_reviews.jsonl');ap.add_argument('--base-url',default=os.getenv('KG_LLM_BASE_URL',''));ap.add_argument('--api-key',default=os.getenv('KG_LLM_API_KEY',''));ap.add_argument('--model',default=os.getenv('KG_LLM_MODEL','deepseek-v4.1-flash'));ap.add_argument('--workers',type=int,default=6);a=ap.parse_args()
 if not a.base_url or not a.api_key: raise SystemExit('Set --base-url and --api-key or KG_LLM_BASE_URL/KG_LLM_API_KEY')
 rows=[json.loads(x) for x in Path(a.input).read_text(encoding='utf-8').splitlines() if x.strip()]
 out=[]
 with ThreadPoolExecutor(max_workers=a.workers) as ex:
  fs=[ex.submit(call,r,a.base_url,a.api_key,a.model) for r in rows]
  for i,f in enumerate(as_completed(fs),1):
   out.append(f.result()); print(f'{i}/{len(fs)}',flush=True)
 out.sort(key=lambda x:x['fact_id'])
 Path(a.out).parent.mkdir(parents=True,exist_ok=True)
 with Path(a.out).open('w',encoding='utf-8') as f:
  for x in out:f.write(json.dumps(x,ensure_ascii=False)+'\n')
 from collections import Counter
 print(json.dumps({'total':len(out),'labels':Counter(x.get('label') for x in out)},ensure_ascii=False))
if __name__=='__main__':main()
