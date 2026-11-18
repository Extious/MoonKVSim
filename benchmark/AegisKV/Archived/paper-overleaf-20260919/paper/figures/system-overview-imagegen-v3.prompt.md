Make a precise final wiring correction to this image. Keep the entire layout, all physical containers, the independent blue Peer copy into Peer Region, both ochre DRAM paths, and the three independent downward retry branches EXACTLY as now. Correct ONLY the following control/request arrows. Image coordinates below refer to the current 1536 x 1024 image.

A. LLM REQUESTS MUST BYPASS THE TRACKER.
Erase the solid vertical line from Agent runtime at (293,138) to Workflow Tracker at (293,257). Erase the solid vertical line from Workflow Tracker at (292,331) to Source GPU at (292,421).
Draw ONE continuous gray solid request path: begin at the Agent runtime bottom-left area (270,137), go LEFT to x=210, go DOWN at x=210 through the empty margin to y=421, ending with a DOWN arrowhead on the Source GPU top border (210,421). This x=210 corridor is OUTSIDE and LEFT OF the Workflow Tracker box. Place "LLM requests" clearly near this bypass. No solid request arrow may touch Workflow Tracker.

B. DAG METADATA MUST GO FROM THE DAG TO THE TRACKER.
The existing dashed metadata line has an incorrect arrowhead pointing into A5 and passes through Offline profiles. Erase this existing metadata connector only. Draw a new gray dashed directed connector STARTING at the right edge of A5, (767,101), with NO arrowhead at A5; go right to x=1094, down to y=175, left to x=396, then down to y=257, with the ONLY arrowhead pointing DOWN into Workflow Tracker at (396,257). The horizontal segment at y=175 passes ABOVE the Offline profiles box and does not touch it. Put "DAG metadata" above the upper segment. Keep the separate Offline profiles -> Placement Planner arrow.

C. BUDGET B: NO ARROWHEAD INTO PEER BUDGET.
The gray dashed path from Peer Budget to Placement Planner is feedback. Remove the downward arrowhead at the TOP of Peer Budget around (1393,489). Keep the connector with its ONLY arrowhead pointing UP into Placement Planner at (846,335). Thus Peer Budget is the source and Planner is the destination.

D. PLACEMENT PLAN: PLANNER IS THE SOURCE.
The dashed path leaving Planner at x=769 and turning toward Backup Agent must have NO arrowhead pointing UP into Planner. Its ONLY arrowhead must point DOWN into the top of Backup Agent near (657,640). Keep the "Placement plan" label.

E. Typography: make text crisp and slightly larger wherever space permits, particularly the small signal labels. Keep a white background, flat pale fills, no shadows or gradients. Do not modify other correct connections or introduce any new arrow. Check all four corrections carefully.
