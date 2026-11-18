# Failure is a required part of workflow KV management

User corrected the position: the motivation must establish the need to handle worker failure, then show that the cited workflow-aware caching work does not incorporate that scenario; it should not define the gap merely as omission of AegisKV's particular WCT valuation.

Rewrote Limitation 2 with four steps: acknowledge dependency-aware cache/scheduling mechanisms; explicitly identify absent serving-worker failure handling and lost in-progress KV; connect the deployment failure concern and long-history reconstruction to Background and the preceding workflow example; explain why surviving offloaded/shared prefixes do not by themselves cover interrupted execution state. The conclusion now states the two complementary gaps and introduces the need to combine workflow-aware KV management with fault tolerance. The Challenges opening follows this combined problem. Detailed challenges and Design are unchanged.

Source scope: checked Parrot OSDI 2024 paper, KVFlow v1, Pythia v2 and TOPAS v1 against their stated designs. The absence claim concerns serving-worker failures and state loss in their workflow-aware policies. Pythia's OOM prevention/preemption recovery and shared-L3 staging remain distinct from worker failure, and the prose continues acknowledging that surviving cache copies can assist recovery. This is a synthesis of mechanism scope, not a claim that no component of those systems ever handles errors or that offloaded KV is unusable for recovery.

Primary sources:
- https://www.usenix.org/system/files/osdi24-lin-chaofan.pdf
- https://arxiv.org/html/2507.07400v1
- https://arxiv.org/html/2604.25899v2
- https://arxiv.org/html/2608.25523v1

Validation: only Limitation 2 and the Challenges opening changed, with matching Chinese text. Nine distinct already-present references support the revised passage; the total bibliography remains 42 entries. All 48 protected sources and figure assets are unchanged. Canonical main.pdf compiled to 23 pages without unresolved references, duplicate labels or overfull boxes. Actual pages 4–5 were visually checked without clipping or overlap.
