# PINN 全骨干权重（physics_thermo10，QM9 多目标，fresh-200 协议）

PINN 有效性研究（「PINN × 5 骨干」记分牌）的完整权重归档。SOTA 家族
DimeNet++ + PINN 在上级目录 `../qm9_pinn_sota_dimenet_pp/`，本目录收录其余骨干。

## delta_e 测试集 RMSE 记分牌（3-seed）

| 家族 | seed42 | seed3407 | seed2026 | 均值 | Δ vs 单任务 | 判决 |
|---|---:|---:|---:|---:|---:|---|
| dimenet_pp（../qm9_pinn_sota_dimenet_pp） | 0.002536 | **0.002274** ★全场最佳 | 0.002370 | **0.002393** | −8.2% | ✅ 绝对最佳 |
| demol（见下方说明） | 0.003225 (ep51 早停) | 0.002361 | 0.002425 | 0.002670 | −12.7% | ✅ transformer 家族最佳 |
| torchmd_net（本目录） | 0.003722 | 0.003706 | 0.003687 | 0.003705 | +12.0% | ❌ 唯一负收益 |
| smiles_transformer（本目录） | 0.008506 | 0.007893 | 0.008534 | 0.008311 | −13.6% | ✅ 相对收益最大 |
| spe_transformer（本目录） | 0.009158 | 0.009065 | 0.009223 | 0.009149 | −4.9% | ✅ |

结论：**4/5 骨干 PINN 为正**，「能提点的 transformer」= DeMol + PINN；DimeNet++ + PINN 为绝对 SOTA。

## 本目录内容

```
{torchmd_net, smiles_transformer, spe_transformer}/
└── {seed42, seed3407, seed2026}/
    ├── best_checkpoint.pt    # torchmd 5.8MB(1.43M参数) / smiles 9.9MB(2.46M) / spe 10.7MB(2.66M)
    ├── config.yaml           # 完整训练配置（含 physics 约束段，同 SOTA 目录说明）
    ├── scalers.json          # train-only per-target Z-score
    ├── metrics.json / test_metrics.json / test_predictions.csv / training_log.csv
    └── COMPLETED.json / environment.json / split_identity.json / *_timing.json
```

- 来源 lane：torchmd_net ← `artifacts/qm9_epoch200/formal_4gpu/runs/`；smiles/spe_transformer ← `artifacts/qm9_epoch200/extension_20261022/runs/`
- 已排除 `checkpoints/`（逐 epoch 历史）与 `resume_backups/`
- 逐文件大小校验与源一致；每家族抽 1 个 checkpoint 经 ai4Chemistry venv torch 实际加载验证
- checkpoint 统一结构：`state_dict / config / scalers / epoch`

## demol（DeMol + PINN）说明

demol 三 seed 的 `best_checkpoint.pt` 各约 **708 MB**（DeMol 为 177M 参数的 3D 等变
transformer，fp32、checkpoint 仅含 state_dict/config/scalers/epoch，无可剥离的优化器状态），
超过 GitHub 单文件 100 MB 硬限制，故**分片入库**：

```
demol/
├── reassemble.sh                 # 一键重组 + 双层校验（分片 sha256 + 整体 sha256）
└── {seed42, seed3407, seed2026}/
    ├── best_checkpoint.pt.sha256 # 完整文件校验值（源文件实测）
    ├── shards/                   # 8 × 90MB 分片 + SHA256SUMS.parts
    │   └── best_checkpoint.pt.part_00 … part_07
    └── （config/metrics/scalers/训练日志等元数据，与其他家族一致）
```

取回完整权重：`bash demol/reassemble.sh`（可只跟一个 seed 名）。分片拼回后的 sha256
已与训练机源文件实测值逐一核对（如 seed42 = `55b7c5fa…31485875`）。
