# System Overview invocation identity — 2026-09-23

The user referenced the live discussion `01a0cd11-d6ef-7082-9359-7b74ba92dc1b` on host `remote-ssh-discovered:gpu10`, asked to show multiple invocations of an Agent, and requested different Agents at the workflow's two ends. Read that thread with `codex_app.read_thread` before using its context. Its relevant distinction is that a Figure 2 branch may aggregate multiple LLM invocations; that discussion does not make the constructed Overview an exact trace reconstruction.

The former A(1)/A(2) endpoints denoted repeated calls of one Agent A. Updated the Overview to six invocation boxes and four Agent identities:

- A(1) → B(1) → B(2) → D(1)
- A(1) → C(1) → C(2) → D(1)

Repeated B calls share a fill, as do repeated C calls. Identity remains explicit in text and readable in grayscale. The caption now defines letters as Agent identities and parenthesized integers as invocation ordinals. Updated the accessibility description as well. Retained the separate invocation-reuse figure and the existing exact-prefix compatibility requirement. No trace timing, Motivation text, or Figure 2 data was changed.

Source: `experiments/scripts/paper/build_design.py`; editable graph: `exports/system-design-current/sources/system-overview.drawio`; constructed node/edge data: `exports/system-design-current/data/overview-workflow.json`. Only Application-band nodes and edges changed; Controller, Engine, callouts, memory objects and their connections are identical to the preceding graph.

Native Draw.io export was initially blocked by sandbox restrictions on Xvfb local sockets. The authorized escalated rerun succeeded. Inspected native PNG and actual column-sized color/grayscale manuscript page 4, plus reflowed pages 5 and 6. Figure geometry remains 84.6825 × 88.2504 mm, minimum type 9.018 pt, with vector graphics. Eight scoped checks in `checks.json` pass. The manuscript remains eight pages and compiles without errors, overfull boxes or unresolved references. Published the active Overview PDF/PNG and `paper/main.pdf`.
