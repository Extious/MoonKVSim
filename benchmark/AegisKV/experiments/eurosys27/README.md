# AegisKV Evaluation 研究稿与实验包

更新：2026-09-23。英文 Evaluation 已拆为 [`paper/evaluation.tex`](../../paper/evaluation.tex)，由 [`paper/main.tex`](../../paper/main.tex) 引入；规范 PDF 为 [`paper/main.pdf`](../../paper/main.pdf)，中文伴读为 [`paper/paper_draft.md`](../../paper/paper_draft.md)。`paper/` 保持六个根 TeX：`main.tex`、`abstract.tex`、`background.tex`、`motivation_and_challenge.tex`、`system_design.tex`、`evaluation.tex`。原始数据、代码、日志和检查记录在 `paper/` 外。

当前方法是 **Peer HBM / DRAM / shared storage 互斥 managed ownership**、校准后固定的每请求 `L/K/Z`、zero-slack Peer admission、lower-tier per-Agent renewable credit 与 lazy updates，以及只调总 Peer 配额的 guarded AIMD。临时迁移副本都计费；Peer 不收租。旧 no-Peer 静态分配器和 isolated rental 结果作为历史诊断保留。

本轮包含 **8 个论文小节、6 张正文图和 1 张补充图**，没有新增物理实验。完整当前控制器的 fault-injection campaign 仍为计划。现有 physical microbenchmark、held-out trace prediction、native access capture、历史 analytical/trace-driven model 分别标注。当前是完整研究稿，不宣称满足 EuroSys 2027 的 12 页限制或已验证整机性能。

## 当前图与证据

| 图文件 stem | 证据级别 | 支持范围与限制 |
|---|---|---|
| `eval-placement-pairs` | 历史 analytical model | 36 个 Peer-disabled 配置，17 改善、19 持平；不是当前 controller |
| `eval-recovery-paths` | 已有 physical worker microbenchmark | 一条输入流、TP2/BF16；HBM/DRAM 三次 timing，其余各一次；不是 Peer/fault campaign，SharedFS 不是 cold SSD |
| `eval-rental-diagnostic` | 历史 additive rental model | 保留原始租金负例和修复后仍落后 direct 的结果；抽象 cost/check count 不是 WCT/CPU |
| `eval-tracker-errors` | Held-out recorded-trace prediction | 1,443 completed-Subagent snapshots / 170 workflows；whole-Agent 标签不能验证 residual-segment Slack |
| `eval-sparse-demand` | Native selector capture 的离线分析 | 3 documents/model、相同 205/512 blocks 预算；历史 frequency 不是现行 normalized estimator 或实测恢复收益 |
| `eval-trace-tails` | 历史 trace-driven FIFO model | 保留 mean 改善、p95/p99 变差；真实 start timing 加假定 workload/queue，不是 serving availability |
| `eval-sparse-horizon`（补充） | Native-trace horizon analysis | 同 document 的 frequency-minus-recency coverage；document min–max 不是 CI |

[`main-figures.json`](main-figures.json)、[`FIGURE_SELECTION.md`](FIGURE_SELECTION.md) 与 [`FIGURE_CATALOG.md`](FIGURE_CATALOG.md) 记录本轮选择、图注与预览。它们应与 `evaluation.tex` 实际引用及当前 manifest 一致。旧图和 CSV 保留，旧选择由 `legacy-main-figures.json` 标识。

## 计划与来源入口

- [`EVALUATION_LITERATURE_20260923.md`](EVALUATION_LITERATURE_20260923.md)：六篇相关论文 Evaluation 原文、图号、实验方法与官方格式要求。
- [`EXPERIMENT_MATRIX.md`](EXPERIMENT_MATRIX.md)、[`PROTOCOL.md`](PROTOCOL.md)、[`campaign-plan.json`](campaign-plan.json)：现行八类研究问题、比较协议和 planned cells；JSON 不是 runner。
- [`DATA_CONTRACT.md`](DATA_CONTRACT.md)：当前逐点表、hash/manifest、未来 campaign pairing、缺失与 censoring。
- [`SUBMISSION_READINESS.md`](SUBMISSION_READINESS.md)：当前交付范围与尚缺的实现/实证。
- [`exports/evaluation-rework-20260922T170350Z/`](../../exports/evaluation-rework-20260922T170350Z/)：`figure-manifest.json`、`plot-data/`、`figures/`、native-source audit 和 `FIGURE_REVIEW.json`。standalone review 不替代最终论文嵌入检查。

主比较为 3 families × 2 models × 4 policies × F0/F1 × 10 paired campaigns，即 **480 planned run slots**。完整 minimum plan 含 **68 cells / 15 comparison blocks / 150 paired campaigns / 1,200 run slots**。它们不是已完成运行、独立 workflow 样本或 GPU-hours；精确计数以 JSON 为准。无可验证 runner 和硬件清单时不启动系统 campaign。

## 重现当前图与论文

从仓库根目录运行。Python 环境需 NumPy/Matplotlib；字体通过 `kpsewhich LinLibertine_R.otf` 获取，编译需 LaTeX/latexmk。下面只读取已有数据，不提交 GPU 作业，也不新增 measured evidence。

```bash
python3 benchmark/AegisKV/experiments/scripts/eurosys27/render_evaluation.py \
  --out benchmark/AegisKV/exports/evaluation-rework-20260922T170350Z \
  --verify-native-sources
```

renderer **没有 `--publish` 选项**。检查七个原生单栏导出后，按 Evaluation 实际引用同步六张 PDF 和中文 PNG；补充图留在实验包：

```bash
python3 - <<'PY_SYNC'
from pathlib import Path
import re
import shutil

root = Path('benchmark/AegisKV')
source = root / 'exports/evaluation-rework-20260922T170350Z/figures'
paper = root / 'paper'
names = re.findall(r'\{figures/evaluation/([^{}]+)\.pdf\}',
                   (paper / 'evaluation.tex').read_text())
assert len(names) == len(set(names)) == 6, names
for name in names:
    for extension, destination in [
        ('pdf', paper / 'figures/evaluation'),
        ('png', paper / 'figures/preview/evaluation'),
    ]:
        destination.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source / f'{name}.{extension}',
                     destination / f'{name}.{extension}')
print(f'Synchronized {len(names)} manuscript figures')
PY_SYNC
sh benchmark/AegisKV/experiments/scripts/paper/build_paper.sh
python3 benchmark/AegisKV/experiments/scripts/eurosys27/check_evaluation.py
```

checker 检查所实现的结构/数据/文稿契约，不证明控制器已实现或物理实验已执行。导出为原生约 84.7 mm 单栏宽、10.3 pt Libertine，仍需查看本次 `main.pdf` 实际插入尺寸、裁切与灰度，不能仅凭源码字号判定合规。构建 auxiliaries 位于 `exports/latex-build/`。

## 历史工具与未来实测

`theory.py`、`expanded.py`、`plot.py`、`plot_expanded.py`、旧 `check_artifact.py`/`check_expanded.py` 和 `measured-template/expanded/` 服务旧模型/图 schema，不再生成当前六图 Evaluation。不要运行旧 `expand_evaluation_text.py` 覆盖新章节，也不要用旧 `--publish` 恢复已移出的主图。历史 `THEORY.md`、export 与 raw tables 保留。

未来当前控制器输出在 `campaign-plan.json.figure_contracts` 中是 `planned_no_data`，尚未注册 renderer。先完成 runner/raw logs/聚合，再新增 measured tables 与绘图支持；不能将 diagnostics 同名换成另一指标或仅改 evidence 字符串。新实测需要同步论文数字、图注、Abstract/Conclusion 和中文，并保存旧版及负结果。
