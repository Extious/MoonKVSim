# Qwen3-8B KV layout artifacts

These files are deterministic E1 source derivations for the pinned
`Qwen/Qwen3-8B` revision and vLLM commit in `reference/source-lock.json`:

- `native-tp1-pp1/kv-layout.json` keeps the model config's native 40,960-token
  limit and `rope_scaling=null`.
- `proposed-yarn-128k-tp1-pp1/kv-layout.json` records the fixed-revision model
  card's 131,072-token static-YaRN candidate as `proposed_unvalidated`.

Regenerate and byte-check them from the repository root:

```bash
uv run python scripts/generate_kv_layout.py \
  --context-mode native --tp-size 1 --pp-size 1 \
  --block-size-tokens 16 --allocator-alignment-bytes 256 \
  --output configs/resolved/qwen3-8b/native-tp1-pp1/kv-layout.json --check

uv run python scripts/generate_kv_layout.py \
  --context-mode proposed-yarn-128k --tp-size 1 --pp-size 1 \
  --block-size-tokens 16 --allocator-alignment-bytes 256 \
  --output configs/resolved/qwen3-8b/proposed-yarn-128k-tp1-pp1/kv-layout.json --check
```

Both artifacts leave live runtime cache capacity as `null` and record vLLM
CacheSpec differential and CUDA validation as `not_run`. They are not physical
validation or formal experiment evidence.
