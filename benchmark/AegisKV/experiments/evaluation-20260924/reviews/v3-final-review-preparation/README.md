# v3 外部评审门禁：准备记录

**已准备，尚未执行 live 完整门禁，也未启动外审或发布。** 准备时主矩阵为
70/180，数值审计、端点、完整后处理和最终整稿尚未就绪。
`PREPARATION.json` 保留该时刻缺项，不随运行进展自动改写。

检查器不导入 runtime、不运行 DES、不构建论文、不调用外部 reviewer、不修改
论文或冻结包。通过时 stdout 只输出 `READY_FOR_EXTERNAL_REVIEW`，退出码 0；
有缺项、旧绑定、读取中变化或未审图时输出 `NOT_READY`，退出码 2。
这始终不等于 paper approved、publication approval 或 goal complete。

## 最终执行命令（现在不执行）

从仓库根目录，在最终产物到齐后手动运行；输出必须是**不存在的新文件**：

```bash
.venv/bin/python benchmark/AegisKV/experiments/evaluation-20260924/reviews/v3-final-review-preparation/check.py \
  --output benchmark/AegisKV/experiments/evaluation-20260924/reviews/v3-final-review-preparation/ATTEMPT-001.json
```

失败后修复实际产物，再使用新的 `ATTEMPT-002.json`；不要覆盖既有 attempt。
通过后再由父任务启动新的完整稿 Opus 外审。本检查器不启动该步骤，也不复用
旧评审的 NOT READY/PASS 为新稿批准。

## 检查范围与真实字段

1. `walltime-primary-v3/STATUS.json` 必须 `complete=true`、`completed_runs=180`。
   核对 180 个 job/COMPLETE/artifacts、原19项协议封存、164个执行源、两模型、
   priors/guard、输出与终态资源门槛。`AUDIT.json` 要求 PASS/180；endpoint
   PROVENANCE 要求 PASS/180 summaries/150 fault rows，并核对
   `WALLTIME_MODEL_PROVENANCE.json` 与新的模型及协议。
2. `PAPER_POSTPROCESS_COMPLETE.json` 的真实成功状态仍是
   `NUMERIC_COMPLETE_VISUAL_REVIEW_PENDING`，不将它改成 PASS。检查其 source seal、
   每个 output hash、model/guard、audit/endpoint、plot/data provenance；检查
   heldout、两条 detailed fallback 和 v2↔v3 对比的实际产物。
3. 16-worker 执行修订的结束记录、原16项完成结果保留哈希和预声明 parallel
   validation 均须通过；再次比较 summary 和解压 event/flow 字节。
4. lowDMA 的 `PACKAGE_COMPLETE.json`（24新条件），native 的 `DELIVERY.json`
   （864 method conditions），quota 的 `FINAL_AUDIT.json`（72条件）及其封存
   closure/审计必须匹配。它们的统计单位与主矩阵不同，不混成独立重复数。
5. 前文按 `PRESERVED_MANUSCRIPT.json` 核对；`main.tex` 只允许此前已授权的
   Evaluation input 和 bibliography inclusion 两处规范化。**七项前文修改的
   permission 仍 pending**。保持前文不变可以提交外审；本门禁不授权那些修改。
6. 解析实际 `evaluation.tex` 的四个 literal `includegraphics`，分别要求绑定
   v3 primary、v2 structural、markers-only resource 和 native-transfer component。
   旧 `eval-native-topk.pdf` 可以留在磁盘，但不能作为第五幅或冒充新 component。
   图的原始 numeric/export/review/seal 依赖同时核查。
7. 当前 `paper/main.pdf` 与 `evaluation.tex` 必须同时匹配最新
   `paper-preview/EXPORT_REVIEW.json` 和 `VISUAL_REVIEW.json`；后者还必须绑定
   前者的 SHA。实际 Evaluation 页段须全部有 color/grayscale 检查和对应 PNG
   hash。TeX **包括注释**不得残留 TODO/NOT_V3_RESULTS/PLACEHOLDER。
8. JSON 从同一份 bytes 计算 SHA 并解析，最终再核所有已读文件哈希，避免混用
   写入前后的输入。所有实际输入哈希写入 gate attempt；配置及检查器自身也封存。

## 唯一新增的最终审图旁证

数值 finalizer 只生成 `figures/FIGURE_METADATA_REVIEW.json`，其状态是等待实际
审图；不能把 metadata 自动视为人工视觉通过。完成 v3 实际尺寸彩色和灰度检查
后，单独新增：

`walltime-primary-v3/figures/VISUAL_REVIEW.json`

该记录的必需字段为：

```json
{
  "status": "PASS",
  "color_and_grayscale_actually_inspected": true,
  "pdf_sha256": "SHA of figures/primary-target-wct.pdf",
  "postprocess_complete_sha256": "SHA of PAPER_POSTPROCESS_COMPLETE.json",
  "render_sha256": {
    "final-size-color.png": "SHA of the inspected color image",
    "final-size-gray.png": "SHA of the inspected gray image"
  }
}
```

可以补 reviewer、时间、尺寸和发现，但不能提前填 PASS。
`PRIMARY_VISUAL_REVIEW_TEMPLATE.json` 只是 pending 模板，未复制到 campaign；
新增旁证不改 frozen postprocess 输出或 COMPLETE，也不改变数值结论。
整稿 EXPORT/VISUAL 沿用已有字段，不强制新增额外 schema。

## 准备验证

`selftest.py` 只使用临时 fixture，覆盖未完成180、缺少实际产物、哈希漂移、
空seal、旧PDF却标PASS、未覆盖最终页、注释内TODO、结束前输入变化和引用图计数。
`SELFTEST.json` 记录结果；这不是真实稿件通过门禁的结果。Ruff 检查同样只作用于
新脚本。独立子代理做只读代码检查，不执行完整门禁。

`CONFIG.json` 固定16个既有身份/封存记录的哈希和四幅期望图的来源。
若以后用户批准前文修改或明确改变输入范围，应另行记录门禁版本修订；不能通过
删除检查、替换旧 seal 或仅改 ready 标签让旧准备记录失去含义。
