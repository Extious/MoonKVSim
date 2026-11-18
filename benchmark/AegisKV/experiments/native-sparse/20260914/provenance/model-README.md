---
datasets:
- openbmb/InfLLM-V2-data-5B
language:
- en
- zh
license: apache-2.0
pipeline_tag: text-generation
library_name: transformers
---

<div align="center">

<h1>NOSA: Native and Offloadable Sparse Attention</h1>


**Boost Decoding Efficiency via High-Locality Offloading**
</div>

<div align="center" style="line-height: 1;">
  <a href="https://github.com/thunlp/NOSA" style="margin: 2px;">
    <img alt="Code" src="https://img.shields.io/badge/GitHub-100000?style=for-the-badge&logo=github&logoColor=white" style="display: inline-block; vertical-align: middle;"/>
  </a>
  <a href="https://huggingface.co/collections/openbmb/nosa" style="margin: 2px;">
    <img alt="Hugging Face" src="https://img.shields.io/badge/NOSA-fcd022?style=for-the-badge&logo=huggingface&logoColor=000&labelColor" style="display: inline-block; vertical-align: middle;"/>
  </a>
  <a href="https://arxiv.org/abs/2510.13602" style="margin: 2px;">
    <img alt="Paper" src="https://img.shields.io/badge/Paper-2510.13602-b31b1b.svg" style="display: inline-block; vertical-align: middle;"/>
  </a>
  <a href="https://huangyuxiang03.github.io/blogs_nosa" style="margin: 2px;">
    <img alt="Blog" src="https://img.shields.io/badge/Blog-000000?style=for-the-badge&logo=googlechrome&logoColor=white" style="display: inline-block; vertical-align: middle;"/>
  </a>
</div>

## Overview

**NOSA** is a trainable sparse attention mechanism designed for KV-cache offloading with an explicit locality constraint, paired with an inference system (**NOSI**) to realize its efficiency. It improves long-context/long-generation quality over prior offloading baselines while boosting decoding throughput by up to **5.04×** vs **FullAttn**, **1.92×** vs **InfLLMv2**, and **1.83×** vs **ShadowKV** on **1B/3B/8B** LLMs.

For more details, please refer to the paper: [NOSA: Native and Offloadable Sparse Attention](https://arxiv.org/abs/2510.13602).

## Models

We train 1B, 3B, and 8B models FullAttn, InfLLMv2, DMA, and NOSA, resulting in a total of 12 models. The following models have been released on Hugging Face.

|Model|Link|
|:-:|:-:|
|NOSA-1B | [NOSA-1B](https://huggingface.co/openbmb/NOSA-1B) |
|NOSA-3B | [NOSA-3B](https://huggingface.co/openbmb/NOSA-3B) |
|NOSA-8B | [NOSA-8B](https://huggingface.co/openbmb/NOSA-8B) |

Please reach out to us if additional baseline models (FullAttn, InfLLMv2, or DMA) are needed. You may open an issue or contact us directly via email (our email addresses are provided in the paper).

## Citation

```bibtex
@article{huang2025nosa,
  title={NOSA: Native and Offloadable Sparse Attention},
  author={Huang, Yuxiang and Wang, Pengjie and Han, Jicheng and Zhao, Weilin and Su, Zhou and Sun, Ao and Lyu, Hongya and Zhao, Hengyu and Wang, Yudong and Xiao, Chaojun and Han, Xu and Liu, Zhiyuan},
  journal={arXiv preprint arXiv:2510.13602},
  year={2025}
}
```