# Evaluation 数据、统计与发布契约

更新：2026-09-23。当前有三类对象：**已生成的七个 evidence figures、历史通用 plotting schema、现行控制器的 planned campaign outputs**。它们不可通过改文件名或 evidence 字段相互替代。当前协议与计划见 `PROTOCOL.md`、`EXPERIMENT_MATRIX.md`、`campaign-plan.json`。

## 1. 当前 evidence figure package

入口为 `experiments/scripts/eurosys27/render_evaluation.py`，输出到 `exports/evaluation-rework-20260922T170350Z/`：`figures/` 的 PDF/SVG/PNG、`plot-data/` 的逐点 CSV、`figure-manifest.json`、native-source audit 和 standalone review。正文选六图，`eval-sparse-horizon` 为补充，清单见 `main-figures.json`。

renderer 读取已有观察/模型，**不执行实验、不接受 `--mode measured`、没有 `--publish`**。七张图各有实际字段，不强行套旧版 x/y schema：

| CSV stem | 实际字段 | 单位与统计对象 |
|---|---|---|
| `eval-recovery-paths` | `path,context_tokens,latency_s,min_s,max_s,timing_repeats,independent_input_streams` | 一个 allocation/input stream；HBM/DRAM 为 3 次 timing 的 median/min–max，其余单次；秒，非 campaign CI |
| `eval-tracker-errors` | `method,workflow_id,agent_id,fold,absolute_error_s,cdf` | 1,443 Agent snapshots/170 workflow clusters，5 workflow-disjoint folds；完整 descriptive ECDF |
| `eval-sparse-demand` | `model,book_id,method,coverage_pct,budget_blocks,total_blocks_per_layer,future_queries` | 3 documents/model、1 checkpoint/document；document points/equal mean；oracle 看未来 demand，线上 ranker 不看未来 |
| `eval-placement-pairs` | `scenario_id,lru_penalty_s,historical_value_penalty_s,paired_reduction_s,cdf` | 36 deterministic configurations，LRU−historical value 秒；independent runs=0 |
| `eval-trace-tails` | `policy,statistic,penalty_s,recovery_episodes` | recorded starts 驱动的 deterministic model，21,738 episodes/policy，非 physical campaigns |
| `eval-rental-diagnostic` | `policy,miss,movement,total,migrations,revalues,scored_hits,credit_refreshes,rejected_with_better_victim,higher_value_victims` | 同一 synthetic candidate/use stream；model cost 与 operation counts，无实验 CI |
| `eval-sparse-horizon` | `model,book_id,future_queries,coverage_gain_percentage_points,frequency_coverage_pct,recent_coverage_pct,blocks_per_layer` | 同 document 配对 frequency−recency，再求 3-document mean/min–max；各 horizon 非独立 checkpoint |

秒、百分比、percentage points、抽象 cost 与 counts 保持原单位。完整 tails、0/negative effects、ties 和负例保留。Sparse coverage 是 distinct future-needed historical physical layer/block bytes，不是 attention mass、累计 traffic 或实测 cache hit。历史 frequency 包含 selector-head/group occurrences，不是当前 per-Query deduplicated visibility probability。

### Manifest 和来源

`figure-manifest.json` 保存 renderer hash、字体/画布、`new_physical_runs=0`，每图 evidence/sources/n/statistics/limitations/caption/table hash/artifact hashes。顶层 `sources` paths 相对 `benchmark/AegisKV/`；artifact paths 相对 export 根；表为 `plot-data/<stem>.csv`。

`--verify-native-sources` 完整校验 upstream native hashes 并保存审计结果；不带此 flag 的重绘读取已有 audit 并检查其 source-manifest 摘要一致。发布前应运行一次完整校验。Physical measurement 的 raw hashes 也由 renderer 核对。Hash 只证明文件身份，不证明实验设计、设备来源或实现正确。

当前标签分别是 physical worker microbenchmark、held-out recorded-trace prediction、offline native-selector analysis、historical analytical/trace-driven/rental model，不能统一改为 measured AegisKV。重绘/重聚合不增加 independent sample count。

## 2. 未来当前控制器的 raw data 与 provenance

`campaign-plan.json.figure_contracts` 的 planned outputs 目前是 `planned_no_data`、`renderer_registered=false`、`output_file=null`。它们是输出意图，不是现成 renderer 支持的空结果。当前完整 runner 未验证，硬件/模型/workload revisions 未冻结。真实 raw logs 和执行证据齐全后才创建 measured manifest。

执行前冻结 code/design/model/tokenizer/kernel/layout、L/K/Z、AIMD/CPU、topology/backend/fault domains、absolute capacities、workload IDs/prompts/tools/DAG、arrival/fault/mapping seeds、SLO/horizon、train/calibration/test 和 tuning budget。原始版本保留；改动产生新 campaign/data version。

`PROTOCOL.md` §7 定义 `runs.jsonl`、`workflows.csv`、`events.jsonl`、`checkpoints.csv`、`controller.csv`、`ownership.csv`、`predictions.csv`、`correctness.csv`、`trace-mapping.csv` 的字段。必须能重建：

- cell/block/campaign/policy/F0/F1/workflow 身份链、run order、host/process/scheduler 来源、状态与失败原因。
- stable owner、temporary duplicates、reservation、copy/commit/redirect/drain、leases、TP/selector completeness、accepted/committed frontiers 和实际 N。
- causal features/native Query observations、materialization versions、per-Agent grant/paid/clock、deduplicated actual-use IDs；analysis-only future labels 与 online features 分开。
- 同一 clock 上的 queue、storage/NIC/H2D、compute/replay、request resume、DAG finish，记录 clock alignment 误差；重叠阶段不能直接相加。

未来 manifest 至少包含以下 metadata；这是字段示例，**不是已生成的 measured 文件**：

```json
{
  "schema_version": 1,
  "evidence": "measured",
  "measurement_class": "physical",
  "design_revision": "ACTUAL_CODE_AND_DESIGN_ID",
  "statistical_unit": "independently launched paired campaign",
  "sample_accounting": {
    "comparison_blocks": "ACTUAL_COUNT",
    "paired_campaigns": "ACTUAL_COUNT",
    "policy_condition_runs": "ACTUAL_COUNT",
    "distinct_workflows": "ACTUAL_COUNT"
  },
  "aggregation_command": "EXACT_EXECUTED_COMMAND",
  "uncertainty": "DECLARED_METHOD_LEVEL_AND_SEED",
  "raw_sources": [
    {"id": "ACTUAL_SOURCE_ID", "path": "raw/workflows.csv", "sha256": "ACTUAL_SHA256"}
  ],
  "tables": {"ACTUAL_REGISTERED_TABLE.csv": "ACTUAL_SHA256"}
}
```

实际文件替换全部占位值并补全 status、exclusions/censoring、backend/fault/version manifests；raw relative paths 从 manifest 所在目录解析。Packager 不能制造 physical provenance。新 metric 必须注册 visual spec，不能复用分母/单位不同的历史图名。

## 3. Pairing、uncertainty 与失败样本

统计层级为 **comparison block → paired campaign → policy/condition run → workflow → request/block/event**。同 campaign 内 workflow 共享故障/资源，不是独立物理运行。10 campaigns、80 run slots、30 distinct workflow IDs 含义不同；重复 30 IDs 十次不变成 300 distinct workflows。

每 campaign/policy/workflow 用该策略自己的 F0/F1 得到 `D=WCT_F1−WCT_F0`；跨策略用 `baseline_D−AegisKV_D`，正值表示 AegisKV 故障增量更小。先在 campaign 内按预定权重汇总，再 bootstrap campaign contrasts（协议初始为 10,000 resamples、95% CI、固定 seed）。不对所有策略减同一个 H-LRU F0，不减不相关 CI 端点构造 difference CI。健康成本另与共同基线 F0 比较。

完整系统测试保留共同原始 arrival cohort；routing/progress-trigger clock 会改变 actual interrupted set，差异属于完整策略效果。仅比较各自 interrupted subset 是描述性结果。机制归因另冻结 pre-fault mapping/coverage/native demand/resources。Deterministic scenarios 无实验置信区间。

每 cell 使用固定 administrative horizon tau。所有 released workflows 留在 completion 分母；timeout/未完成无 eventual WCT，不填 0 或伪造 finish。报告 completion fraction 和 `mean(min(T,tau))`，未完成项贡献 tau，并注明 finite-horizon restricted cost。共同 complete-case latency 只是 selection-sensitive 的次要结果；缺 anchor/crash/OOM/unsupported 的原因单列，不当 benign independent censoring。

ECDF 保留 tails/0/负值并说明权重。预测统计按 workflow clusters，native traces 按 document/checkpoint，calendar replay 按 source-system/window/故障簇，不能把相关 events 当重复 campaigns。五个 factorial blocks 必须四角配对齐全后算 `(Y11−Y10)−(Y01−Y00)`。

## 4. 旧通用 schema 与工具

旧 `plot.py`/`plot_expanded.py` 的 schema 为 `figure,panel,series,x,y,lower,upper,unit,evidence,scenario_id,source_id,independent_runs`；expanded 另有 `category`。它们服务旧注册 metric，不能直接读取第 1 节七种表。Analytical 的 `independent_runs=0`，physical aggregation 应记录独立 campaigns 而非 requests/blocks。区间端点需同时、有限、有序；无 CI 则留空，不编造。

`aggregate_workflows.py` 是旧 paired complete-case mean/difference helper，拒绝缺策略/条件 mates，保留 completion ledger；不实现全部当前 planned metrics，也不能替代 finite-horizon/censoring analysis。`prepare_measured_figures.py` 接收已聚合且符合旧 spec 的 physical tables/raw manifest，仅包装 provenance。`measured-template/expanded/` 是旧模板；空白不是 0，模板个数不是 campaign 数。

旧 packaging 要求 `measurement_class=physical`、真实 raw hashes、非空 aggregation/statistical/sample metadata、`evidence=measured`、`independent_runs>=1`。通过代码检查不等于硬件已执行。未来新图先添加 renderer/schema/aggregation checks；在此之前不宣称任意新 CSV 都能自动发布。

## 5. 重绘、发布与文稿同步

完整命令及按 TeX references 复制六图的步骤见 `README.md`：

```bash
python3 benchmark/AegisKV/experiments/scripts/eurosys27/render_evaluation.py \
  --out benchmark/AegisKV/exports/evaluation-rework-20260922T170350Z \
  --verify-native-sources
# 按 README 的 TeX-reference 同步步骤复制经过检查的六张主图。
sh benchmark/AegisKV/experiments/scripts/paper/build_paper.sh
python3 benchmark/AegisKV/experiments/scripts/eurosys27/check_evaluation.py
```

PDF 主图在 `paper/figures/evaluation/`，中文 PNG 在 `paper/figures/preview/evaluation/`；补充图/SVG 留在 export。保持六个根 TeX 与规范 `paper/main.pdf`。Checker 只验证所实现的结构、来源/表/图与统计契约，不证明 physical execution；最终仍需实际插入尺寸的彩色/灰度 PDF 检查，所有图文至少 10 pt。

未来实测替换需保存原版，同步 Abstract/Evaluation/captions/Conclusion/中文与 manifest，明确证据类型。不要运行旧文字脚本覆盖 `evaluation.tex`，或由旧 renderer 的 `--publish` 恢复过时主图。计划完整、figure checker 通过与 LaTeX 成功，都不表示现行整机性能已验证或满足 12 页 submission-ready 要求。
