# experiments

当前设计（并行 retry、Slack 优先放置、层序 × 热度选块）所依赖的数据、实测与脚本。
旧的 Qwen3-8B DP=8 模拟实验栈（configs / workloads / scripts / results）已整体归入
`../Archived/simulation-qwen3-8b/`。

| 路径 | 内容 |
|---|---|
| `data/motivation-real-cc/` | CC / Weka 124 个工作流的分支重建 CSV（图 1、图 2） |
| `data/recompute-aiconfigurator-a100/` | 图 4 参照曲线：Qwen3-8B、Qwen3-30B-A3B 在 A100-SXM 上 8K–128K 完整前缀 prefill 的 AIConfigurator 估计（`estimate_recompute_a100.py` 调用锁定的 0.9.0 checkout，HYBRID 与 SOL 两种模式，含逐算子来源）；MiniCPM4-8B 不被该工具支持 |
| `native-sparse/20260914/` | NOSA-1B 选块轨迹（`traces/`）、pg19 文本（`provenance/`）、`capture_native.py`（NOSA 系列采集脚本，仍被 2026-09-15 的任务调用） |
| `native-sparse/20260915/` | MiniCPM4-8B 选块轨迹、prefill / 重放时延（`prefill-latency-*.json`、`replay-latency-*.json`）、交叉模型表（`*_models.csv`、`SUMMARY_MODELS.json`）、`analyze_models.py`（默认纳入 NOSA-3B，交叉模型表为三模型版）、全部 `*.sbatch` 与 Slurm 日志、`figure1/4-expansion-status.json`（文件名沿用 2026-09-15 的图号，对应现图 2 与图 5）。图 2 与图 3/4/7 的代价模型使用 `*-minicpm4-8b-a100-152626.json`（`measure_minicpm4_a100.sbatch`：A100 80GB PCIe，协议 v2 保留全层 KV，8K–128K 实测，同一分配内测重放代价）；`*-retained-kv-151751.json`（RTX 4090，三模型）与旧协议文件仅作为归档版重算图的来源保留，渲染脚本不再读取 |
| `native-sparse/20260915-nosa-3b/` | NOSA-3B 32K 选块轨迹（任务 151771，已进入正文图 6） |
| `native-sparse/20260915-minicpm4.1-8b/` | MiniCPM4.1-8B 权重校验记录（下载在任务 151797 中因节点无外网中断，待在有网络的节点重跑 `prepare_minicpm41.py`） |
| `native-sparse/runtime-20260914/` | 测量用运行环境：venv、NOSA-1B/3B/8B 与 MiniCPM4.1-8B 权重、HF 缓存（MiniCPM4-8B）、triton / uv 缓存、上游源码；约 55 GB，git 忽略 |
| `native-sparse/runtime-20260915/` | InfLLM-v2 CUDA kernel 源码与构建日志（任务 150349） |
| `scripts/paper/` | `render_draft_20260915.py`（图 1–4、6–9）、`build_draft_overview.py`（图 5） |

所有脚本和 sbatch 都以仓库根目录 `/home/comp/zhanzhao/MoonKVSim` 为工作目录；
`*.log` 是历史运行记录，其中的旧路径（`output/…`、`tmp/…`）未改写。
