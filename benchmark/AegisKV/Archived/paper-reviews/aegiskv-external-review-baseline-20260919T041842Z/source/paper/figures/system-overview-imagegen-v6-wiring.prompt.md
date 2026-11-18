Correct the attached AegisKV figure locally. Preserve the three tiers, all top and middle content, matching DP panel sizes, white style, and existing DP0 content. No new components.

A. MIRROR ONLY THE DP1 INTERIOR so transport endpoints are correct:
- In DP1 HBM, the LEFT half must be pale blue labeled "Peer KV"; the RIGHT half pale gray labeled "Local KV". Keep the split into two halves, HBM heading, and local-read note.
- The LEFT module in DP1 (the one touching the BLUE inter-DP arrow and GOLD DRAM arrow) must read "Connector", subtitle "KV transfer".
- The RIGHT module in DP1 must read "Adapter", subtitle "KV management & recovery".
This is a mirror of DP0, with the two Connectors facing each other across the center. Keep DP0 Adapter on the LEFT and Connector on the RIGHT.
- The blue double arrow must connect DP0 Connector directly to DP1 Connector. The gold D2H/H2D arrows must connect DRAM store to the Connector of EACH DP, never to Adapter. With the above swaps the existing blue and gold paths should already have the correct endpoints. Do not move those blue/gold arrows.
- Preserve short black local HBM/interface connections, which indicate local access, not another cross-GPU copy.

B. CLEAN CONTROL-ARROW ENDPOINTS:
Erase the three gray dashed lines currently extending into HBM or down toward Connector. Redraw them ONLY in the clear gap between Planner and the TOP BORDERS OF THE DP PANELS, not through any HBM contents:
1. Placement plan: from bottom of KV Placement Planner DOWN to DP0's top outer panel boundary near its upper-right area. Only ONE arrowhead, DOWN at DP0. No arrowhead at Planner.
2. Block ranks: a separate line from DP0's top outer boundary UP into Planner, only ONE arrowhead at Planner. No arrowhead at DP0.
3. Peer capacity: from DP1's top outer boundary UP into Planner, only ONE arrowhead at Planner. No arrowhead at DP1.
Keep labels next to their own lines in whitespace. These messages target the whole DP engine; no gray control line should penetrate HBM or terminate at Connector.

C. FIX RED RETRY DESTINATION:
Erase the existing long diagonal red dashed arrow that ends between the DP1 modules. Redraw a red dashed path from Recovery Coordinator to the RIGHT-HAND DP1 Adapter. Route it through the free gutter along the RIGHT edge of DP1, outside its HBM bar, and terminate with one clear LEFT-pointing arrowhead on the RIGHT edge of the Adapter box. It must not pass through HBM text, KV tiles, or module labels. Keep "Concurrent retries" in nearby clear space. Keep Failure Detector -> Recovery Coordinator red arrow and DP0 red failure X.

No other changes. Do not reintroduce Offline calibration. Final check: both DP0 and DP1 have Local KV + Peer KV HBM, Adapter, and Connector; the two connectors exchange peer KV, and both connect to DRAM.
