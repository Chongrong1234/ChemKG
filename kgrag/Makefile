.PHONY: install serve test eval build-index clean

install:            ## 可编辑安装（含 dev 依赖）
	pip install -e ".[dev]"

serve:              ## 启动 Web 服务（默认 0.0.0.0:8600）
	python3 run.py

test:               ## 运行单元测试
	python3 -m pytest tests/ -v

eval:               ## 检索回归评测（silver 集）
	python3 scripts/eval_retrieval.py --gold ../evaluation/auto_silver.jsonl --strategy kg --k 5

build-index:        ## 从 kg_data 重建索引
	PYTHONPATH=src python3 -m kgrag.cli build --kg ../kg_data --out ../rag_index

clean:              ## 清理缓存
	find . -name "__pycache__" -type d -exec rm -rf {} + ; rm -rf .pytest_cache
