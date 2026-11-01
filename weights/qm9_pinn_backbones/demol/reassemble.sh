#!/usr/bin/env bash
# 从分片重组 demol 各 seed 的 best_checkpoint.pt（708MB/个，超 GitHub 100MB 单文件限制而分片入库）
# 用法: bash reassemble.sh [seed42|seed3407|seed2026]   # 缺省重组全部三个 seed
set -euo pipefail
cd "$(dirname "$0")"
SEEDS="${*:-seed42 seed3407 seed2026}"
for s in $SEEDS; do
  echo "== $s =="
  (cd "$s/shards" && sha256sum -c SHA256SUMS.parts)
  cat "$s"/shards/best_checkpoint.pt.part_* > "$s/best_checkpoint.pt"
  (cd "$s" && sha256sum -c best_checkpoint.pt.sha256)
  echo "$s/best_checkpoint.pt 重组完成 ($(stat -c %s "$s/best_checkpoint.pt") bytes)"
done
