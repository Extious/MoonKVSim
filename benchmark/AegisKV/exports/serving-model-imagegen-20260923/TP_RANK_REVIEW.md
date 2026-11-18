# Per-rank KV correction

User correction: “没有将 TP 每个 rank 的 KV 细节展示出来”. This supersedes the earlier decision to reduce TP to a group label.

The selected raster study is `serving-model-tp-ranks.png`. Two built-in imagegen edits were made using `TP_RANK_PROMPT.txt` and `TP_ALIGNMENT_PROMPT.txt`, starting from `serving-model-concept.png`.

## Checked semantics

- Each worker is one illustrative TP=2 model replica, with two contained compartments named Rank 0 and Rank 1.
- Both ranks of Worker 0 have Agent B and Agent E. Both ranks of Worker 1 have Agent C and Agent F. Requests are dispatched to the worker, not split by agent across TP ranks.
- Every agent in every rank has explicitly labeled K and V bars under Local KV shards. Rank containment supplies shard ownership. Exact head assignment, replication rules and physical tensor dimensions are deliberately unspecified; this is not a universal claim of equal non-overlapping KV partitions for every model configuration.
- In both Worker 0 ranks, B's K/V prefix and appended suffix have aligned boundaries. The B1-to-B2 reuse/append example applies to the rank-local tensors for the same token progress.
- All ten workflow-DAG edges and the B2/E1 versus C1/F1 request assignments remain unchanged. Both worker-bottom output paths join the external collector and return to accepted histories outside the workers.

The first per-rank edit introduced inconsistent illustrative token-block dividers in some K/V rows. A targeted second edit replaced these with unsegmented tensor bars, retaining only B's meaningful prefix/append boundary. It also routed the right-side return line outside Worker 1. The corrected native image was visually inspected.

## Placement scope

Rendered at 84.68 mm width in color and grayscale (`review/tp-ranks-column-*`). Agent/rank identity, K/V pairing and the split-region legend remain structurally discernible. Text is still too small for the current manuscript's 10 pt target at this width, as with the previous imagegen study; raster text is not being certified by PDF font metadata. This delivery is a concept preview. A final editable redraw needs typographic reallocation and another actual-size review.

The canonical paper figure has not been replaced by this raster study. Previous drafts and prompts remain available. User aesthetic acceptance has not been inferred from this edit request.
