---
license: llama3.1
library_name: transformers
base_model:
- meta-llama/Llama-3.1-8B-Instruct
base_model_relation: "adapter"
---


# SeerAttention-Llama-3.1-8B

This is a reproduction of the [SeerAttention](https://arxiv.org/abs/2410.13276) paper. The model contains additional learnable AttnGate modules on top of [meta-llama/Meta-Llama-3-8B-Instruct](https://huggingface.co/meta-llama/Llama-3.1-8B-Instruct). The AttnGate modules accelerate long-context attention inference by enabling block-level sparsity. During training, the AttnGates are optimized via self-distillation while keeping the original model weights frozen. Specifically, the AttnGates learn to mimic the 2D-maxpooled outputs of the attention maps. At inference time, the soft scores produced by the gates are converted into binary masks, thereby reducing both the I/O overhead and computational cost of the attention mechanism.



## Original Github Repo
[https://github.com/microsoft/SeerAttention](https://github.com/microsoft/SeerAttention). 

## Evaluation Results

### Perplexity on PG19
| Density | 8192  | 16384 | 32768 | 65536 | 131072 |
|---------|-------|-------|-------|-------|--------|
| 1.00    | 10.03 | 9.88  | 9.92  | 9.97  | 10.03  |
| 0.50    | 10.04 | 9.89  | 9.92  | 9.99  | 10.05  |
| 0.40    | 10.06 | 9.89  | 9.93  | 9.99  | 10.07  |
| 0.30    | 10.09 | 9.91  | 9.95  | 10.01 | 10.15  |
| 0.20    | 10.19 | 9.94  | 9.97  | 10.04 | 10.37  |
| 0.10    | 10.61 | 10.08 | 10.04 | 10.09 | 10.88  |

### LongBench

With threshold set to 2e-3. 

| Task                 | 0-4k  | 4-8k  | 8k+   |
|----------------------|-------|-------|-------|
| 2wikimqa             | 51.1  | 47.85 | 33.36 |
| gov_report           | 35.03 | 35.05 | 34.57 |
| hotpotqa             | 63.97 | 60.0  | 56.7  |
| lcc                  | 67.98 | 73.18 | 65.28 |
| multi_news           | 28.1  | 25.78 | 24.25 |
| multifieldqa_en      | 58.63 | 51.45 | 51.87 |
| passage_count        | 18.0  | 10.15 | 11.88 |
| passage_retrieval_en | 100.0 | 99.0  | 98.0  |
| qasper               | 47.77 | 44.04 | 39.63 |
| repobench-p          | 51.78 | 56.24 | 56.75 |
| samsum               | 43.28 | 41.19 | 45.29 |
| trec                 | 64.0  | 76.0  | 75.0  |
| triviaqa             | 90.91 | 88.45 | 92.43 |
| averaged             | 55.43 | 54.49 | 52.69 |


### RULER

|       | Dense Baseline | SeerAttn | Avg density |
|-------|---------------:|---------:|------------:|
| 4k    |         95.53  |    95.53 |        0.87 |
| 8k    |         92.27  |    92.71 |        0.72 |
| 16k   |         92.01  |    92.02 |        0.56 |
| 32k   |         87.63  |    88.49 |        0.46 |
| 64k   |         84.39  |    83.48 |        0.32 |
| 128k  |         76.26  |    73.37 |        0.17 |