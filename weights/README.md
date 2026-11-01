# QM9 小模型权重（DimeNet++ 六性质 × 三 seed 集成）

KG-RAG 分子计算 agent 的后端推理权重，即 `kgrag-molprop.service` 实际加载的 18 个 checkpoint（2026-11-02 从训练机产物归档）。

## 内容

```
qm9_dimenet_pp/
├── {alpha,homo,lumo,mu,r2,zpve}/     # 六个 QM9 性质
│   └── {seed42,seed3407,seed2026}/   # 三个配对随机种子
│       ├── model.pt                  # checkpoint（state_dict，约 7.6 MB/个）
│       ├── config.yaml               # 模型结构参数（六性质一致，共用模板）
│       ├── target_scaler.json        # 目标值归一化参数（推理必需）
│       ├── normalization.json        # 输入特征归一化
│       ├── metrics.json              # 测试集指标
│       └── predictions/ 等           # 训练环境与过程记录
```

共 18 个 `model.pt`，总计约 137 MB。

## 来源与用途

- 训练产物原路径：`ai4Chemistry/artifacts/qm9_six_properties/high_formal_a100_v1/runs/dimenet_pp/`（A100 正式训练）
- 服务加载方：`kgrag/scripts/molprop_service.py`（`RUNS_ROOT` 指向上述原路径；模型构造采用「单模板 + deepcopy」，加载 `state_dict` 时依赖 `config.yaml` 与 `target_scaler.json`）
- 对外接口：`POST /predict`（SMILES → 六性质，3-seed 输出 mean ± std，离散度即不确定性），由 KG-RAG 主服务的 agent 工具经 `http://127.0.0.1:8601` 调用

## 适用范围与许可

- 元素范围与 QM9 一致：**仅 H / C / N / O / F**，超出即报错（如含 S 的分子）
- 能量单位 Hartree（服务同时换算 eV），μ 为 Debye，α 为 Bohr³，R² 为 Bohr²
- 权重来自本课题组自训模型，随本仓库同许可（见根目录 LICENSE）

## 子目录

- `qm9_dimenet_pp/` — 生产权重：单任务 DimeNet++（molprop 服务实际加载）
- `qm9_pinn_sota_dimenet_pp/` — 研究线 PINN SOTA：DimeNet++ + physics_thermo10 多目标（delta_e RMSE 全场最佳，含记分牌与物理约束说明）
