# AIConfigurator and target-model notes

AIConfigurator is locked at commit
`4b9d9dc51e02b5e9d4acc3688f3edf41693834c6`, package version `0.9.0`.
The hash-verified audit in `reference/aiconfigurator-support.json` used that
repository's isolated environment and real SDK. Qwen3-8B, L40S, A100-SXM and
A100-PCIe source descriptions exist, but the only materialized L40S/A100-SXM
vLLM databases are for vLLM `0.14.0`; A100-PCIe has no vLLM database. The SDK
reports Qwen3-8B aggregate/disaggregate support for L40S and A100-SXM at
`0.14.0`, and reports the target vLLM `1.2.2` unsupported on all three systems.
SGLang and TensorRT-LLM tables are explicitly ineligible for a vLLM profile.

The nearest vLLM `0.14.0` Qwen3-8B BF16 tables stop at prefill extension
16,384 and decode past-KV 32,767, and their SDK coordinates cannot preserve an
arbitrary mixed per-request vector. The checked-in eight-scenario SDK golden is
therefore E2 reference semantics only: it is not target-version compatibility,
target calibration, or performance evidence. `formal_use_allowed=false` and
`SRC-BLOCK-001` remains unresolved.

The formal selection schema/loader requires exact target/database version
identity, a materialized database bundle, and materialized residual report,
raw evidence, held-out split, and predeclared-threshold files. It rejects
symlinks, traversal, size/hash drift, noncanonical/unknown fields, a global
scale factor, and residual reports whose profile/phase/shape/counts or
threshold result do not match the selection. Unsupported/preliminary state is
recorded only in the support audit, not in the formal selection schema.

No target calibration bundle exists. Physical forward calibration is outside
the current E2 simulation-only delivery, so M3 remains below E3.

The local Qwen3-8B cache provides revision
`b968826d9c46dd6066d109eabc6255188de91218`; its tokenizer and embedded chat
template are locked. This does not prove 128K model execution: the model config
has `max_position_embeddings=40960`, `rope_scaling=null`, while tokenizer
metadata says `model_max_length=131072`. A source-pinned long-context policy
and matched vLLM validation are required before the 128K gate can pass.

AIConfigurator predicts only GPU forward. Scheduler CPU, connector metadata,
Mooncake RPC, Store, KV transfer, network, reroute and recovery are separate
MoonKVSim resources and must not be folded into a global scale factor.
