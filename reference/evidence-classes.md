# Evidence classes

| Class | Required evidence | Claims allowed |
|---|---|---|
| E0 design | specification, schema, source map | proposed contract only |
| E1 static | implementation, type/lint/unit tests | code exists and static gates pass |
| E2 semantics | golden/differential traces and byte-identical ledger replay | modeled control flow and accounting |
| E3 calibration | component measurements with raw traces and held-out error | calibrated component range only |
| E4 end-to-end | matched physical vLLM+Mooncake and simulator runs | measured simulator accuracy for that setup |
| E5 paper | complete matched matrix, repeats, confidence intervals, provenance audit | paper conclusions |

Evidence never upgrades implicitly. Every result manifest records its highest
demonstrated class and any fidelity gaps.
