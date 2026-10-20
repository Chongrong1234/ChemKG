#!/bin/bash
# auto_pipeline.sh — 等待五模型评审全部完成后自动执行聚合、CSV 导出、一致性分析
set -u
# 在仓库根目录运行；LLM 凭据通过环境变量提供，切勿硬编码
cd "$(dirname "$0")/.."
: "${KG_LLM_BASE_URL:?请设置 KG_LLM_BASE_URL（OpenAI 兼容接口地址）}"
: "${KG_LLM_API_KEY:?请设置 KG_LLM_API_KEY}"

MODELS="deepseek-v4-pro-0813 glm-5.3-shouyun qwen3.7-max qwen3.6-plus kimi-k2.6"
NEEDED=218

echo "$(date '+%H:%M:%S') 开始监控评审进度..."
while true; do
    all_done=1
    status=""
    for m in $MODELS; do
        f="jury/reviews__${m}.jsonl"
        n=$(python3 -c "
import json, sys
try:
    lines = [json.loads(l) for l in open('$f', encoding='utf-8') if l.strip()]
    print(sum(1 for x in lines if x.get('label') and x.get('label') != 'api_error'))
except FileNotFoundError:
    print(0)
" 2>/dev/null)
        status="${status} ${m}=${n}"
        if [ "${n:-0}" -lt "$NEEDED" ]; then
            all_done=0
        fi
    done
    echo "$(date '+%H:%M:%S')${status}"
    if [ "$all_done" = "1" ]; then
        echo "$(date '+%H:%M:%S') 全部模型完成 ${NEEDED} 条评审"
        break
    fi
    # 若评审进程已死且未完成，重启
    if ! pgrep -f 'llm_jury.py' > /dev/null; then
        echo "$(date '+%H:%M:%S') 评审进程不在运行，重启..."
        setsid nohup python3 kg_pipeline/llm_jury.py \
            --input strict_extraction_v2/relations.jsonl \
            --out jury \
            --base-url "$KG_LLM_BASE_URL" \
            --api-key "$KG_LLM_API_KEY" \
            --models "deepseek-v4-pro-0813,glm-5.3-shouyun,qwen3.7-max,qwen3.6-plus,kimi-k2.6" \
            --workers 10 >> jury_run.log 2>&1 < /dev/null &
        disown
    fi
    sleep 300
done

echo "$(date '+%H:%M:%S') === 运行共识聚合 ==="
python3 kg_pipeline/jury_aggregate.py \
    --facts strict_extraction_v2/relations.jsonl \
    --jury jury \
    --golden-out golden_benchmark_v2 \
    --seed 2025 > jury_aggregate.log 2>&1
echo "聚合完成 exit=$?"

echo "$(date '+%H:%M:%S') === 导出 CSV ==="
python3 kg_pipeline/export_v2_csv.py > export_csv.log 2>&1
echo "CSV 导出 exit=$?"

echo "$(date '+%H:%M:%S') === 人工签核一致性（占位，等人工填写后重跑）==="
python3 kg_pipeline/jury_consistency.py > jury_consistency.log 2>&1 || true

echo "$(date '+%H:%M:%S') === 全部完成 ==="
