# Pinned vLLM notes

- Repository: `/home/comp/zhanzhao/.tmp/aegiskv-1cat-vllm-v1.2.2-sm89-src`
- Commit: `644d8a7cd05ed4ecd1cd188e3c05b4bbd074f504`
- Tree: `f38216c408682c421e2f20462cb1651009b3ed03`
- Exact tag: `v1.2.2`
- Remote: `https://github.com/1CatAI/1Cat-vLLM.git`

The tree is a 1CatAI fork, not an assumed stock vLLM checkout. The generated,
ignored `_version.py` reports `1.2.2+aegiskv.sm89`; all scheduler, KV and
connector semantics are nevertheless read from the pinned Git objects listed
in `source-lock.json`.

M2 KV layout also locks `vllm/config/model.py` from this commit. In
`ModelConfig.get_num_kv_heads`, the per-rank KV-head count is
`max(1, total_num_kv_heads // tensor_parallel_size)`. MoonKVSim must therefore
preserve GQA/MQA head replication when tensor parallelism exceeds the total KV
head count; dividing to zero is not a valid abstraction.

The Qwen3-8B 128K vLLM arguments recorded in `source-lock.json` are a
`proposed_unvalidated` candidate derived from the fixed-revision official model
card. They remain `BLOCKED` pending physical validation on this exact vLLM
commit, including representative short contexts because static YaRN may affect
their performance.

The worktree reports one untracked build directory. It is not a patch and is
excluded from source mapping. Future differential tests must still establish
that the mapped behavior is reproduced by MoonKVSim.
