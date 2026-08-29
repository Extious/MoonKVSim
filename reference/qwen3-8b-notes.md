# Pinned Qwen3-8B model-card notes

- Model: `Qwen/Qwen3-8B`
- Revision: `b968826d9c46dd6066d109eabc6255188de91218`
- Fixed model card:
  `https://huggingface.co/Qwen/Qwen3-8B/blob/b968826d9c46dd6066d109eabc6255188de91218/README.md`
- Model-card Git blob: `ecc3ebd0849aa08d9484bd911dddfd5261b10d30`
- Resolved README SHA-256:
  `0f36caaff9c2516411a7738db384606263ba653c1e63e61d72f511606164d5a6`

The official model card supplies this vLLM long-context candidate:

```text
rope_type=yarn
factor=4.0
original_max_position_embeddings=32768
max_model_len=131072
```

This is configuration guidance, not MoonKVSim experiment evidence. The lock
therefore records `status=proposed_unvalidated`, `readiness=BLOCKED`, and
`formal_128k_allowed=false`. Static YaRN applies one scaling factor regardless
of input length and the model card warns that it may affect shorter-text
performance. Formal use requires physical long-context and representative
short-context validation on vLLM commit
`644d8a7cd05ed4ecd1cd188e3c05b4bbd074f504` and the target hardware.
