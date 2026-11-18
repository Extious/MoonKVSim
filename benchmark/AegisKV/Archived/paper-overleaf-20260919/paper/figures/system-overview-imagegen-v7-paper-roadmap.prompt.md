Use case: infographic-diagram.
Create a new precise AegisKV System Overview for a systems research paper, revising the supplied older candidate. Keep THREE horizontal tiers and restrained 2D visual grammar, replace the architecture as below. A deployment overview and paper roadmap, not an algorithm flowchart. Mooncake is the technical substrate, not a style reference.

STYLE: white background, crisp modest black outlines, restrained rounded corners, pale gray modules, blue Peer KV, pale ochre DRAM, muted red recovery commands. No perspective, shadows, gradients, hardware art, oversized headings, equations, long paragraphs. Landscape approximately 1.3:1. Large readable English labels and generous arrow gutters. Three tier frames: Applications; Control Plane; Inference Engines.

APPLICATIONS: compact top tier. Left request card: "LLM request", "Workflow ID", "Node ID", "Dependencies". Right "Agent runtime" with small "Workflow DAG": A branches to B/C, both join D then E. Runtime -> request connector labeled "DAG metadata". Request arrow DOWN into Router.

CONTROL PLANE: middle tier. LEFT compact "Router", subtitle "Request dispatch". RIGHT larger "AegisKV Controller", subtitle "Store Master extension". This controller is a policy extension hosted with Master; no competing second Master.
Inside Controller top row: "Workflow Tracker" with black circular badge 1; "KV Placement Planner" with black circular badge 2. Short gray dashed Tracker -> Planner arrow labeled "Slack". Secondary bottom row: small unnumbered "Recovery Manager" beside pale-gray foundation strip "Replica directory / Membership". These are metadata services, not KV bytes.
Router -> Workflow Tracker gray dashed arrow "DAG metadata". Recovery Manager -> Router muted red dashed arrow "Retry target", routed in clear whitespace, precisely ending at Router. Do not expand P90/CPM or draw tier tables or offline calibration.
Router dispatches "Requests / retries" by thin black branches to BOTH DP panels below. A SEPARATE gray dashed bidirectional control bus joins Controller to BOTH DP boundaries, labeled "Plans / KV status / health". Clearly marked ports on boundaries are acceptable. Route in whitespace, no text/line collisions. No KV data through Controller or Router.

INFERENCE ENGINES: bottom tier with two matching DP panels "DP0" and "DP1" side by side. Each has:
- "KV HBM" horizontal bar, pale gray "Local KV" taking about three quarters and pale blue "Peer KV" about one quarter. No percentages printed. DP0 Local left / Peer right; DP1 Peer left / Local right. Only KV pool shown.
- "Adapter" with black circular badge 4, subtitle "KV management & recovery".
- "Connector" with black circular badge 3, subtitle "KV transfer". INSIDE each Connector, two slim pale gray backend labels "Store Client" and "Transfer Engine", representing reused Mooncake libraries.
Mirror arrangement: DP0 Adapter left / Connector right; DP1 Connector left / Adapter right. BOTH complete and equivalent. Short black interface connections Adapter-to-HBM, Adapter-to-Connector, Connector-to-HBM. Brief note "Peer KV: local read" beneath each memory bar. Same badge numbers for same module types on both DPs.
Across central gutter connect two CONNECTOR boxes using solid BLUE DOUBLE-HEADED arrow "Peer KV transfer". Endpoints touch Connectors, never Adapters. Beneath DPs inside same tier shared ochre strip "DRAM KV Store (Mooncake)". Each Connector has ITS OWN ochre double-headed arrow to store, labeled "DRAM transfer". Peer and DRAM copies independent, never a required Peer->DRAM cascade. No third GPU, failure X, permanent source/recovery names or PP ranks.

BADGES: BLACK circles with WHITE numerals, do not cover text: 1 Workflow Tracker; 2 KV Placement Planner; 3 BOTH Connectors; 4 BOTH Adapters. Reading pointers, not steps. Do not number arrows.
Small footer legend: black solid "Requests / interfaces"; gray dashed "Control"; blue solid "Peer KV"; ochre solid "DRAM KV"; red dashed "Retry command". No prose caption inside image.

CHECK: three tiers; Router plus Master-hosted Controller; summarized workflow policy; replica metadata and membership in control plane; both DPs same capability and small Peer region; Adapter engine integration, Connector Store/Transfer backends; KV data bypasses control plane. All endpoints clear and labels legible.
