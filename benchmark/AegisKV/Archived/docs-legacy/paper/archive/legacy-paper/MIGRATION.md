# Paper migration record

This paper tree was imported on 2026-08-16 from
`/home/comp/zhanzhao/sglsim/AegisKV`. The source tree was untracked in the
SGLSim checkout, whose checkout anchor was
`ca1fe76e88959a2bac0f6060e3042dc2c7d4f855`.

The imported snapshot is identified by these SHA-256 values:

- `design/current_design.md`:
  `915886a3fbca8270eb55c1e5867f4c01bff1b0edaa48ab0294972a3392a20682`
- `paper/main.tex`:
  `789219a9ff7a77262f949652900ef1b8442c277283f04cc35a9a4cfd6f82f0de`
- `paper/sections/03-system-design-v2.tex`:
  `b2c1f6e4324106839a87dc12203bc79d6ba030f3b9a552219ef65e0961a3ef04`
- `paper/sections/05-evaluation.tex`:
  `80b897f36f97c28af805941fda7e1abfb0b7d899320bc32c239da7592f1d7eb7`
- `paper/references.bib`:
  `12310f11500ea2b6e89d1bb7535a6e20a19e658b77915b18c72103ca561cd28b`

The design document remains the source of truth. The Mooncake prototype and
the paper must evolve together, but imported simulator or modeled results are
not runtime evidence for this implementation. The initial physical evaluation
is deliberately restricted to Qwen3-8B, four independent TP=1/PP=1 vLLM
workers, and system-level DP=4 on one four-V100S node.

