# PINN SOTA 权重：DimeNet++ + physics_thermo10（QM9 多目标，fresh-200 协议）

**PINN 实验线的全场 SOTA**：在 ai4Chemistry「fresh-200 协议 × PINN × 5 骨干」记分牌上，
DimeNet++ + PINN 取得最佳 3-seed 平均 RMSE（delta_e），其中 **seed3407 = 0.002274 为全部
PINN 实验的最佳单次 RMSE**（实测 metrics.json，优于文档曾标注的 demol_pt10_3407 = 0.002361）。

## delta_e 测试集 RMSE 记分牌（PINN 各骨干，3-seed）

| 骨干 + PINN | seed42 | seed3407 | seed2026 | 3-seed 均值 |
|---|---:|---:|---:|---:|
| **dimenet_pp（本目录）** | 0.002536 | **0.002274** ★ | 0.002370 | **0.002393** ✅ 最佳 |
| demol | 0.003225(ep51 早停) | 0.002361 | 0.002425 | 0.002670 |
| torchmd_net | 0.003722 | 0.003706 | 0.003687 | 0.003705 ❌(+12%) |
| smiles_transformer | 0.008506 | 0.007893 | 0.008534 | 0.008311 |
| spe_transformer | 0.009158 | 0.009065 | 0.009223 | 0.009149 |

seed3407 全目标 RMSE：homo 0.001525 / lumo 0.001736 / **delta_e 0.002274** / alpha 0.2965 /
mu 0.08896 / r2 6.046 / zpve 0.000508（Hartree 制，除 mu=Debye、alpha=Bohr³、r2=Bohr²）。

## 物理约束（variant = physics_thermo10）

- 热力学一致性损失：ΔE = LUMO − HOMO（gap 容差 1e-4 Ha）+ 焓约束（容差 1e-6 Ha）
- 约束权重 0.1，warmup 10 epoch + 线性爬坡 10 epoch；监督损失 MSE，按 val_delta_e_mae 选点
- 单模型多目标：同时输出 homo/lumo/delta_e/alpha/mu/r2/zpve 七目标（对比生产版每性质一个单任务模型）

## 内容与来源

```
seed42|seed3407|seed2026/
├── best_checkpoint.pt    # 8.9 MB，2.21M 参数；keys: state_dict/config/scalers/epoch
├── config.yaml           # 完整训练配置（含 physics 段）
├── scalers.json          # train-only per-target Z-score（推理必需）
├── metrics.json / test_metrics.json / test_predictions.csv / training_log.csv
└── COMPLETED.json / environment.json / split_identity.json / *_timing.json
```

- 来源：`ai4Chemistry/artifacts/qm9_epoch200/formal_4gpu/runs/dimenet_pp_physics_thermo10_seed{42,3407,2026}/`
- 已排除 `checkpoints/`（逐 epoch 历史，240MB/seed，非归档必需）
- 逐文件大小校验与源一致；`best_checkpoint.pt` 已用 ai4Chemistry venv torch 实际加载验证
- 训练协议：fresh-200（200 epoch / batch 256 / patience 20 / train-only Z-score / test-only 终评），seed3407 跑到 ep199

## 与生产服务的关系

`kgrag-molprop.service` 加载的是**单任务版** `weights/qm9_dimenet_pp/`（六性质逐项精度全面更优，
见上级 README 对比）。本目录是研究线 PINN SOTA 归档：多目标 + delta_e 场景下的最强 PINN 模型，
用于 PINN 有效性结论（4/5 骨干为正、DimeNet++ 绝对最佳）的证据留存与复现。
