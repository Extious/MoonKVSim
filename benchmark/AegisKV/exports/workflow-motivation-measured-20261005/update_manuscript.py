"""Update the existing Motivation only after all required new measurements finish."""
from pathlib import Path
import json
ROOT=Path(__file__).resolve().parent;AEGIS=ROOT.parents[1]
meta=json.loads((ROOT/'ORIGINAL_TYPE_MEASUREMENTS.json').read_text())
assert 'isolated_cost' in meta and len(meta['native_concentration'])==3
text=r'''\section{Motivation}\label{sec:motivation}

A failed Agent can reconstruct its KV cache from durable inputs or restore a surviving checkpoint~\cite{strati2024dejavu,cao2026lumen}. Reconstruction repeats prefill of its accumulated history; checkpointing consumes capacity and transfer resources during normal execution. We examine these costs using the research-report and repository-review DAGs described in Section~\ref{sec:background:serving}, retaining the established workflow, recovery-cost, and access-concentration views.

\subsection{Full KV Protection Is Expensive}\label{sec:motivation:cost}

Our pilot executes a comparative research task and an Astropy issue review on frozen public source materials. With Qwen3-4B-Instruct-2507, BF16 KV, and two independent L40S replicas, the applications produce 36 invocations across 15 Agents. Each Agent makes two to four sequential calls; all 21 follow-up calls reuse a compatible historical prefix. Source collection precedes the measured stage, which performs no online tool calls. The research Agent A grows from 3,089 to 6,381 cached positions over four calls; the review Agent A grows from 13,555 to 16,110 over three calls. Their measured KV tensors grow from 0.424 to 0.876\,GiB and from 1.861 to 2.212\,GiB, respectively.

Using six complete input prefixes from these new executions, we separately measure full prefill and pinned-host-to-GPU restoration of every layer's KV tensors. At 15,917 input tokens, the tensors occupy 2.186\,GiB; full prefill averages 1.329\,s and the complete H2D copy averages 0.102\,s over three repetitions. The copy interval excludes checkpoint creation and subsequent inference. These measurements separate recomputation and transfer costs on naturally occurring application contexts. Protecting every growing history also multiplies checkpoint bytes across concurrent Agents; the required capacity therefore depends on the active workflow population, rather than a single request's context.

\subsection{O1: Agents Have Unequal Recovery Value}\label{sec:motivation:agent}

Figure~\ref{fig:agent_value}(a) shows measured Agent-task intervals for the research-report DAG. D requires A and B; E requires A and C; F requires B and D; G requires E and F. B completes early, while the observed A--D--F--G path determines completion. A task's start depends on its own predecessors, allowing tasks from different graph levels to overlap. Dashed extensions show retrospective timing tolerance computed from these observed intervals and explicit dependencies.

For Figure~\ref{fig:agent_value}(b), we replay the newly generated input and output tokens on the GPUs and remove only one Agent's KV after its first invocation. The model weights and durable tokens remain available. A, B, C, and G are selected before observing the outcomes; each has three counterbalanced healthy/loss pairs. The left bars show measured first-forward prefill time after the loss, divided into the normal appended-input cost and additional reconstruction cost. The right column reports the independently measured signed WCT change. A request-local reconstruction cost is consequently distinct from an end-to-end workflow delay, which also reflects parallel work and serving-resource scheduling. The paired WCT observations vary across repetitions, including negative differences; they do not provide an absorbed-delay decomposition.

For an isolated delay with other execution fixed, the timing relation is
\begin{equation}
\Delta W_i=\max(0,R_i-\sigma_i),\label{eq:isolated_penalty}
\end{equation}
where $R_i$ is the additional delay and $\sigma_i$ the remaining DAG slack. This relation explains the role of workflow position; Figure~\ref{fig:agent_value}(b) uses recorded WCT rather than values calculated from this equation. A worker failure can also remove several Agent states, whose effects interact at shared joins and recovery resources. Selecting checkpoints should therefore account for their joint effect on the remaining workflow.

\begin{figure}[t]
\centering
\begin{subfigure}{\columnwidth}
\centering
\includegraphics[width=0.88\linewidth]{figures/agent_value_a.pdf}
\caption{Measured research-report task intervals.}
\end{subfigure}
\vspace{0.15em}
\begin{subfigure}{\columnwidth}
\centering
\includegraphics[width=0.88\linewidth]{figures/agent_value_b.pdf}
\caption{Recovery prefill and measured workflow change.}
\end{subfigure}
\caption{Agent recovery in the new research-report DAG. (a) First healthy GPU replay: measured task intervals including queues, with critical path and slack derived from explicit dependencies and observed durations. (b) Three matched, counterbalanced KV-loss pairs per Agent. Hatched/solid segments are healthy prefill/extra reconstruction; bars are mean loss-prefill time with min--max ranges. $\Delta W$ is independently measured. Its three-pair ranges for A/B/C/G are $[0.13,8.52]$, $[-0.04,0.004]$, $[-0.02,0.12]$, and $[-0.05,0.02]$\,s. All paired input/output tokens are identical.}
\label{fig:agent_value}
\Description{Seven Agent tasks A through G execute the research-report DAG. The longest observed path is A, D, F, G. Four predeclared isolated KV-loss cases show physical prefill costs and separately measured signed workflow completion changes; WCT differences include negative results and vary across repetitions.}
\end{figure}

\subsection{O2: KV Regions Have Unequal Recovery Value}\label{sec:motivation:kv}

Figure~\ref{fig:kv_value} repeats the native sparse-attention observation on three complete successive request histories from the newly executed review Agent A. These histories contain 16,381--19,933 tokens under each sparse model's tokenizer. For NOSA-8B, NSA-8B, and MiniCPM4.1-8B, respectively, the hottest approximately 20\% of complete historical blocks account for @NOSA@\%, @NSA@\%, and @MINICPM@\% of the recorded query--block selection counts, averaged across layers and histories. The observation preserves each published model's native attention selection; instrumented and uninstrumented logits agree exactly.

Concentrated selections identify uneven historical demand, but a retrospective count is distinct from future cache coverage or a recovery-latency gain. During layer-ordered restoration, computation can hide some transfers; only exposed waiting affects completion. A complete backing checkpoint avoids full-history reconstruction, whereas immediately available HBM regions can reduce the remaining transfer stalls. Their benefits should therefore be evaluated separately.

\begin{figure}[t]
\centering
\includegraphics[width=\columnwidth]{figures/kv_value.pdf}
\caption{Historical KV selection concentration on the new review workflow. Models are NOSA-8B~\cite{huang2026nosav2}, NSA-8B~\cite{fasa2026minicpm4nsa}, and MiniCPM4.1-8B~\cite{openbmb2025minicpm41}. Each curve uses the final 512 queries of three complete successive Agent-A request histories, re-tokenized from their full text. A complete historical 64-token block counts once per query across heads; per-layer shares are averaged over 32 layers and histories. Bands show the range across these three histories, which are successive states of one input. Ranking is retrospective; the plotted counts cover the selected raw-KV branch, excluding separate compressed and sliding-window paths. Budgets are rounded down to whole blocks.}
\label{fig:kv_value}
\Description{Three native selection-concentration curves with mean and history-range bands. Approximately twenty percent of historical blocks cover @NOSA@, @NSA@, and @MINICPM@ percent of query-block counts. These are native selection observations, not runtime HBM-hit or recovery-speedup measurements.}
\end{figure}

\subsection{O3: Replication Capacity Changes over Time}\label{sec:motivation:adaptation}

Fast replicas share HBM with foreground inference. The captured calls show changing resident KV and temporary execution memory as Agent histories grow and tasks complete. In this bounded pilot, per-worker post-call allocated memory peaks at 10.52\,GiB on 44.42\,GiB L40S devices. These observations quantify demand changes without imposing a saturated-memory workload. Under higher concurrency, a fixed replication allocation can compete with execution state, while a small allocation can leave available capacity unused. Adaptive admission must track safe capacity and be assessed together with foreground latency under changing load.

\paragraph{Summary.}
The new workflows expose evolving per-Agent histories, explicit parallel dependencies, and nonuniform native historical demand. Workflow-aware protection must distinguish Agent-level completion impact from request-local recovery cost, distinguish complete recovery coverage from fast-tier acceleration, and track changing foreground capacity. Section~\ref{sec:design} describes how \system{} realizes these requirements.
'''
for marker,row in zip(['NOSA','NSA','MINICPM'],meta['native_concentration']):
 text=text.replace('@'+marker+'@',f"{row['top20_mean_percent']:.2f}")
path=AEGIS/'paper/motivation.tex'
assert path.exists()
path.write_text(text)
print('Updated existing',path)
