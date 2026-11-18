# KV 优先级的条件理论核对

配套方法文档：[REQUEST_KV_POLICY_SPEC_20260914.md](../../../benchmark/AegisKV/docs/paper/REQUEST_KV_POLICY_SPEC_20260914.md)。

本目录只做精确有理数算术核对：逐层计算/传输递推与闭式、等字节放置比较、Slack 饱和上限、可分情形的离散分配，以及多分支 WCT 互补反例。这里的枚举不是模型运行、请求仿真、故障实验或性能测量，也不取代文档中的条件证明。

在项目根目录执行：

```bash
python3 output/analysis/kv-policy-theory-20260914/derive_policy.py
```

只使用 Python 标准库，输出写入本目录。`checks.json` 给出核对数量及条件；CSV 保留构造例的数值；`MANIFEST.json` 记录脚本、文档和被只读审计的运行时代码指纹。指纹对应工作区文件，不把本地 HEAD 当成未提交修改的完整版本，也没有联网刷新远程分支。
