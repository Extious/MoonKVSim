# Serving model: TP attention detail

This edit continues the user's image-generation preview, following the questions about whether each rank owns full per-token KV and whether attention needs KV all-gather. It preserves the teacher's original workflow-serving narrative and the latest per-rank cache requirements.

The example is explicitly standard head-parallel MHA with 8 Q heads, 8 KV heads, TP=2, one illustrative transformer layer. Rank 0 owns heads 0–3 and Rank 1 owns 4–7. Each owns its assigned heads over the full visible token history. GQA/MQA replication and context parallelism are outside this particular example. Output-projection contributions are summed within each worker; historical KV is not gathered across ranks.

Input: ../serving-model-imagegen-20260923/serving-model-tp-ranks.png.
Teacher source: /home/comp/zhanzhao/.codex/attachments/51b5e2eb-2a6c-4e05-9e1a-b05197b1492d/已粘贴的文本.txt, paragraphs on worker mapping and local TP shards.
Primary technical reference: https://research.nvidia.com/labs/adlr/MegatronLM/, self-attention head partitioning and row-parallel output projection, verified in this conversation.

Requested output is an updated generated image concept. Preserve prompts and originals. Keep the current editable manuscript figure separate from the generated study; final manuscript typography must be reviewed at the existing 84.68 mm width before any paper integration.
