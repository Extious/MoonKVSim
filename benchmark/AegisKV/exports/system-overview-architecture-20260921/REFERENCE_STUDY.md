# Overview visual references

User supplied these two PDFs on 2026-09-21. Both complete PDFs were downloaded and their relevant pages rendered and inspected locally. Web PDF screenshots were unavailable; final local renders, rather than intermediate partial downloads, informed the drawing.

## LiveUpdate

Source: [Near-Zero-Overhead Freshness for Recommendation Systems via Inference-Side Model Updates](https://arxiv.org/pdf/2512.12295#page=6), Figure 7, printed page 6.

The figure nests CPU memory and GPU resources inside node boundaries. Tables and caches have concrete visual identities and repeated nodes convey distribution. Two colored paths distinguish concurrent activities. A side panel expands the trainer's mechanisms without making that panel the entire architecture.

Transferable principle: let placement and state ownership determine the large regions; draw data objects where they live. AegisKV uses its own compute-worker, control-service and backing-store boundaries. It does not import LoRA training or the reference's memory layout.

## RACER

Source: [When KV Meets Embeddings: Dynamic GPU Memory Allocation for Accelerating Generative Recommender Serving](https://arxiv.org/pdf/2605.04450#page=5), Figure 7 on printed page 5; Figure 3 on page 3 was also inspected.

Figure 7 separates a global router, a serving fleet, and an expanded node. Inside the node, execution and memory ownership remain visible alongside its local control component. Figure 3 additionally depicts cache entries inside explicit CPU/GPU memory regions and distinguishes local from network movement.

Transferable principle: distinguish global dispatch from node-local execution and shared state. AegisKV depicts two worker boards with GPU/HBM and places shared KV backing outside them. It does not adopt embedding-cache partitioning or a node-local allocation controller.

## Application to AegisKV

The preceding square layout fixed aspect ratio but still emphasized a sequence of labeled modules. The revision gives the main area to concrete serving and storage resources: a global Router with KV-map and load summaries; GPU/HBM inside two equal worker boundaries; side control and recovery metadata; and shared DRAM/SSD objects connected by a KV transfer fabric. Worker-state feedback and control/transfer-status links close the control loop. The retry arrow is an example, not a permanent primary/standby assignment.

The final drawing is independently constructed native Draw.io XML. References provide visual organization only. Kept the current DRAM/storage algorithm, single-column placement, near-square aspect ratio, and explicit protected-failure-domain assumption.
