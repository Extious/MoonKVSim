# BLSC-A100 存储清理候选：2026-09-19

本次为只读盘点，未删除文件、未申请 GPU。根目录为 `/home/bingxing2/home/scx8q31`。平台针对该目录的 `df -h` 显示配额 300G、使用 294G、剩余约 6.9G；整个 NFS 卷的剩余空间不能替代账户可用额度。

## 建议优先清理

| 对象 | 精确范围 | 保守可释放空间 | 影响 |
|---|---|---:|---|
| pip 下载缓存 | `/home/bingxing2/home/scx8q31/.cache/pip` | 9.45 GiB | 后续安装可能重新下载软件包；不包含已安装环境 |
| Conda 压缩安装包 | `/home/bingxing2/home/scx8q31/miniconda3/pkgs` 顶层的 `*.conda` 和 `*.tar.bz2`，共 444 个 | 5.31 GiB | 后续重建环境可能重新下载；不清理解压后的包目录 |
| Conda 索引缓存 | `/home/bingxing2/home/scx8q31/miniconda3/pkgs/cache` | 0.69 GiB | 下次查询软件源重新下载索引 |

三项合计 **15.45 GiB**，不含目录本身少量开销。清理后剩余空间预计约 **22 GiB**，能容纳本轮约 14.19 GiB（15.23 GB）的 Qwen2.5-7B-Instruct-1M 权重，并留下部分依赖空间；依赖安装前仍需核算余量。

上述数字来自实际分配的磁盘块。pip 的 1170 个文件、Conda 的 444 个压缩包和 64 个索引文件均为单硬链接文件；未把与环境共享硬链接的空间算作可释放容量。结束核查时没有发现本账号的 pip、uv、conda 等包管理进程；缓存文件引用仅涉及本次只读 `du` 扫描。执行删除前需刷新进程、文件身份与配额检查。

## 次要候选

`/home/bingxing2/home/scx8q31/.cache/uv` 的单硬链接文件约 **0.75 GiB**，另有约 4.2 MiB 多硬链接文件。本轮未完成所有环境对 uv 缓存的符号链接检查，因此不计入优先清理总量，也不建议直接整目录删除。

## 应保留的内容

- `/home/bingxing2/home/scx8q31/models`：约 **98.81 GiB**，包含 Qwen3-32B、Qwen2.5、Llama 和 InternViT 等模型；没有把它们判定为废弃模型。
- `/home/bingxing2/home/scx8q31/miniconda3/envs/megatron-reft`：现有 ARM64 PyTorch 2.9.1/CUDA 12.8 环境，本轮测量准备复用。
- `/home/bingxing2/home/scx8q31/apps/cuda-compat-12.8`：现有 CUDA 兼容库。
- `/home/bingxing2/home/scx8q31/Megatron_Reft`、`/home/bingxing2/home/scx8q31/Megatron_Reft_old`、`/home/bingxing2/home/scx8q31/LoRCK_baseline` 以及实验数据、checkpoint、代码历史：未完成逐项用途与引用审核，不能仅按名字含 old/backup 判断可删除。当前仍有 5 个 REFT 作业处于依赖等待或挂起状态。
- `/home/bingxing2/home/scx8q31/.cursor-server`：约 2.73 GiB，查询时有编辑器进程在运行，不列为整目录清理对象。

模型和缓存的定向统计已完成；全 home 扫描在覆盖优先候选后停止，避免继续遍历无关研究目录。因此本报告不声称已完整审核所有历史实验产物。

原始 inode、磁盘块和主要文件记录见同目录 `storage-audit-20260919.json`。本报告提供候选范围，不代表已获删除授权。
