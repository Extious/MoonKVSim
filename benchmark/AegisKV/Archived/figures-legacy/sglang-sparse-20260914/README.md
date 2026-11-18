# 基于本机 SGLang 的稀疏选择与 KV 装入图

2026-09-14。用户授权使用本机 Mooncake 或 SGLang 绘制稀疏注意力相关图像。本轮选择 SGLang 的原生 DSA / HiSparse 路径作为代码来源，未修改两个项目的实现。

本轮完成的是**源码机制图，以及本机 PyTorch 参考函数在明确构造输入上的执行结果**。训练模型运行数为 0、CUDA kernel 运行数为 0；没有真实 attention 权重、模型热点分布、H2D 时延或故障 WCT 测量。两组层输入与 16 个 Query 行不是独立实验重复。

## 1. 本机实际条件

- SGLang：`/home/comp/zhanzhao/sglang`，分支 `multi-level-backup`，本轮 HEAD 以 `reference_trace.json` 记录的完整 SHA 为准（短 SHA `dce5a12be0`）。已有未跟踪目录 `benchmark/aegiskv_mooncake/`；未改动它。
- Mooncake：`/home/comp/zhanzhao/Mooncake`，短 SHA `719735896`，分支 `aegiskv`。该工作区已有修改，本轮只读检查。
- 当前节点 `nvidia-smi` 返回无法与 NVIDIA 驱动通信。没有据此推断集群其他计算节点也没有 GPU。
- 在常用 HuggingFace cache 中发现 Qwen3-0.6B、Qwen3-4B、Qwen3-8B 等稠密模型快照；该范围未发现原生稀疏权重。在所查 SGLang benchmark/tools 与 MoonKVSim output 文件名中也未找到可直接使用的 indexer/top-k 稀疏轨迹。这不是对整台机器所有存储路径的穷尽扫描。
- 使用 SGLang 自有 `.venv` 中的 Torch，在 CPU 上执行其测试代码的两个纯 PyTorch 参考函数。绘图使用 MoonKVSim `.venv` 的 Matplotlib 与 PyMuPDF。

## 2. 图像、数据与可支持结论

### 图 1：逐 Query 选取与位置频次

![本机 SGLang 参考输出](/home/comp/zhanzhao/MoonKVSim/output/pdf/sglang-sparse-20260914/sglang-per-query-selection.png)

[PDF](sglang-per-query-selection.pdf) · [SVG](sglang-per-query-selection.svg)

固定 M=16、N=8、k=4，两组独立层索引分数输入。每行 Query 只允许选择自身及之前位置，蓝色为前 M 个已备份历史 token，绿色为重放区间 token，灰色为不可见的未来位置。后 N 个 token 在相应层已经产生的 KV 可以成为因果可见的候选；图没有把候选限制为 HBM。

脚本从本机 `sgl-kernel/tests/test_topk.py` 的 AST 中提取 `_ref_torch_impl` 与 `_ref_torch_transform_decode_impl`，保留函数体不变，单独在 CPU 执行，避开 GPU 测试模块的导入副作用。来源文本、行号和哈希均保留。每 Query 的 seq_len 随位置增加；未来分数特意设置得很大，以核对它们仍不能被选入。

**重要边界：本例有意在输入中设定持久高分位置。** 执行参考函数验证了选取、因果范围与索引映射的计算，不证明训练好模型自然具有这种集中性。索引分数也不是主 attention softmax 权重，访问频次图不能改名为“吸收的注意力质量”。k=4 是便于阅读的参考函数配置，不代表本机生产 CUDA kernel 支持这种启动形状。

第 1、2 层各有 32 次 token 选择，其中旧历史 24 次、重放区间 8 次；各自的旧历史需求并集均为 6/16。最后的比例来自构造分数，不能当作论文中原生稀疏模型的观测。

### 图 2：选 token 与搬运物理块的差别

![逻辑选块与物理需求](/home/comp/zhanzhao/MoonKVSim/output/pdf/sglang-sparse-20260914/sglang-selection-to-physical-blocks.png)

[PDF](sglang-selection-to-physical-blocks.pdf) · [SVG](sglang-selection-to-physical-blocks.svg)

沿用图 1 层 1 的输出。Query 17 选择旧历史位置 {1,4,9}，另选择当前位置 17。若假设每次必须按连续的 1、4、8-token 整块装入，首 Query 所需历史覆盖分别为 3、8、16 个 token；八个 Query 的需求并集分别为 6、12、16 个 token。

这是**同一个逻辑选择集合，在三种假定传输粒度下的算术映射**。没有将三种粒度声称为本机 HiSparse 已支持或实测的配置。按需装入后不逐出时，并集是历史工作集大小；实际重载、预取错误及资源阻塞会改变传输次数与时延。

本机 HiSparse 的 Host pool 使用 `page_size=1`，CUDA swap-in 代码按 `item_size_bytes` 复制需要的 MLA token entry。不能仅因为 index-K 存储或其他页表使用 64-token 页，就说一次稀疏访问必然搬运 64 个主 KV。若论文备份管理选择更大的 chunk，应重新检查是否允许从备份块中按 entry 读取；允许细粒度读取时，图中的整块放大假设就不适用。

### 图 3：HiSparse 已有路径与 Retry Prefill 扩展

![HiSparse 装入与恢复路径](/home/comp/zhanzhao/MoonKVSim/output/pdf/sglang-sparse-20260914/sglang-hisparse-recovery-path.png)

[PDF](sglang-hisparse-recovery-path.pdf) · [SVG](sglang-hisparse-recovery-path.svg)

这张图直接依据本机代码：索引器需要本层 Query 与 index-K/scale 等状态；Decode 得到逻辑 Top-k 后，由 HiSparse 使用 request ID、layer ID 解析当前设备缓存，命中项直接使用、未命中项从 Host 装入，当前最新 token 使用本地保留槽，之后运行稀疏 attention。

图中 S={1,4,6,7} 是手工给定的单步 Decode 初始驻留例，沿用同样的 Query 17 选择 {1,4,9,17}，得到两个历史命中、一个历史装入、一个本地当前 token。这是集合分类，不是实际执行 CUDA cache lookup，也没有执行 LRU 或计时。不能将 Decode 的 newest-token 特例直接套用成 batched Prefill 中“每个 Query 都有一个独立最新槽”。

在当前 `nsa_backend.py` 中，`forward_decode` 调用 `swap_in_selected_pages`；所读 `forward_extend` 路径只将位置翻译为已有设备位置，未调用同一 swap-in 接口。因此可以借用其选择和装入机制，但**已有 Decode 优化并不等于请求重试时的稀疏 Prefill 已经完成按需恢复支持**。虚线框表示拟议扩展，不是已经实现的代码。

## 3. 精确代码来源与论文意义

| 来源 | 本轮确认的含义 |
|---|---|
| [Top-k 参考函数](/home/comp/zhanzhao/sglang/sgl-kernel/tests/test_topk.py:13) | 在指定合法范围内选逻辑位置，普通 paged 路径再映射物理位置；两函数已在 CPU 执行 |
| [Indexer 的返回索引契约](/home/comp/zhanzhao/sglang/python/sglang/srt/layers/attention/nsa/nsa_indexer.py:118) | 变换结果不一定仍是原 logits 的列索引；真实轨迹必须标明坐标空间 |
| [HiSparse 强制未融合逻辑 Top-k](/home/comp/zhanzhao/sglang/python/sglang/srt/layers/attention/nsa_backend.py:2142) | 本机 HiSparse Decode 的索引由 coordinator 解析；不能提前套普通 paged 映射 |
| [Decode swap-in 调用](/home/comp/zhanzhao/sglang/python/sglang/srt/layers/attention/nsa_backend.py:1534) | 选择后按层、按请求解析并装入需要的 KV |
| [Prefill 设备位置翻译](/home/comp/zhanzhao/sglang/python/sglang/srt/layers/attention/nsa_backend.py:1381) | 本轮所读分支未提供相同的 Host 按需装入调用 |
| [逐层缓存状态](/home/comp/zhanzhao/sglang/python/sglang/srt/managers/hisparse_coordinator.py:88) | device token/loc 与 LRU 状态都含 layer 维度 |
| [Host pool 初始化](/home/comp/zhanzhao/sglang/python/sglang/srt/managers/hisparse_coordinator.py:44) | Host 侧 `page_size=1`、`layer_first`；不等同于其他页表粒度 |
| [生产 swap-in kernel](/home/comp/zhanzhao/sglang/python/sglang/jit_kernel/csrc/hisparse.cuh:179) | 最新 token 特例、当前命中与 LRU 排序、随后复制缺失 entry；本轮仅源码审查 |
| [跨层索引复用配置](/home/comp/zhanzhao/sglang/python/sglang/srt/models/deepseek_v2.py:1207) | 存在 `index_topk_freq/pattern` 可复用前层选择；不能泛称同一 Query 在所有层必然重新选择 |

注意：目录名 `nsa` 在这份实现中包含 DeepSeek DSA 的路径，不能因此将它等同于早期 NSA 论文的压缩/选择/窗口三分支模型。图 1 用独立层输入，不开启跨层索引复用；这个条件应随真实模型配置一起记录。

本轮也核对了 [SGLang 官方 HiSparse 说明](https://docs.sglang.io/docs/advanced_features/hisparse_guide)，其说明小型 GPU KV 缓存、完整 Host 存储和按需装入，定位为 Decode 侧优化；在线版本还可能包含本地 checkout 没有的功能。模型与 backend 命名见 [官方 Attention Backend 文档](https://docs.sglang.io/docs/advanced_features/attention_backend)。本轮图像以记录的本机版本为准。

对论文而言，“少量 HBM + Host 中完整 KV + 原生稀疏按需读取”本身已有实现基础。我们需要明确增加的部分：固定 Retry DP 的可靠备份与所有权、相同 M 覆盖下的恢复前驻留决策、M+N 状态的重试 Prefill 时间线、Workflow WCT/Slack 估值及租金维护。不能把现有 HiSparse 的正常 Decode 缓存机制当作新的故障收益证据。

## 4. 怎样用真实访问记录替换构造输入

后续有实际模型/执行环境时，优先记录同一请求的 `request_id, model_revision, layer_id, query_position, phase, M, N, route_epoch`，以及**恢复前可得**的逻辑 Top-k 位置、对应物理块、初始 HBM 驻留、index-K 等辅助状态就绪情况。跨层复用要记录来源层；每次索引的坐标空间必须明确。

需要分别出图的量为：逐 Query 选择矩阵、原始位置频次、恢复窗口物理需求并集、故障前决定的驻留集合覆盖情况，以及实际首次加载/重载与暴露等待。注意力质量图还需要主 attention 权重，不能从 indexer Top-k 直接恢复。

记录应在原生选择之后观察结果，不能改变选择域，也不能把实际来自未来的选块结果输入故障前放置策略。读取 GPU tensor 的追踪操作可能同步设备；追踪运行的时延不能默认作为正常推理时延使用。

## 5. 复算与导出

从 MoonKVSim 根目录依次执行：

```bash
PYTHONDONTWRITEBYTECODE=1 OMP_NUM_THREADS=1 /home/comp/zhanzhao/sglang/.venv/bin/python output/pdf/sglang-sparse-20260914/extract_reference.py
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python output/pdf/sglang-sparse-20260914/plot_sparse.py
```

`reference_trace.json` 保存构造分数、参考输出、检查与源文件指纹；`selected_entries.csv` 保存逐次选择。图像保留 PNG/PDF/SVG 和可编辑绘图脚本。最终宽度假设为 178 mm，交付前检查真实 PNG 和 PDF 渲染；审查状态见 `REVIEW.json`。没有修改运行时代码、主论文正文或旧图。
