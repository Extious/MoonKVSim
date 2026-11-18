#!/usr/bin/env python3
"""Request-centered reading diagram; Credit alternatives are not implementation."""
from __future__ import annotations

import hashlib
import importlib.util
import json
import subprocess
from pathlib import Path
from urllib.parse import quote, unquote

OUT = Path(__file__).resolve().parent
BASE = OUT.parent / "algorithm-flows-v3/build_flowcharts.py"
spec = importlib.util.spec_from_file_location("aegis_flow_base", BASE)
assert spec and spec.loader
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)
m.OUT = OUT

b = m.Book("request-kv-production-and-admission")
p = b.page("R", "算法 2：从一次请求到每个 KV chunk 的备份决策",
           "主线按现有 revision 3 展开；Priority 是当前收益密度。右侧历史 Credit 是待选机制，未接入主线。",
           ("① 请求执行与 KV 生产", "② 每个 tier 的当前状态决策", "③ Priority 与 Credit 的定义边界"))
p.n(0, "arrive", "请求到来，绑定唯一调用 ID\n确定模型身份、路由和保护目标", 235, 110)
p.n(0, "context", "记录当前 Slack、恢复代价模型和有效期\n关联已存在的兼容共享前缀\n管理对象是 chunk；调用提供价值上下文", 415, 145)
p.n(0, "produce", "执行 Prefill / Decode，逐步生成主 KV\n持续生产；每个完整 chunk 触发保护评估", 640, 125)
p.d(0, "sealed", "本次有完整、不可变\n且源仍可读的新 chunk？", 900, 175)
p.n(0, "register", "注册 chunk：内容身份 / 父链 / bytes\n追加到该调用已生成的 KV 路径\n刷新恢复代价；不复制尚未生成的 KV", 1190, 150)
p.n(0, "tiers", "分别进入 Peer HBM / Store DRAM\n两层分别从 Source 复制", 1415, 90, color=m.PURPLE)
p.box("end", "请求结束：退出活跃收益；共享引用 / TTL / FreeACK 清理见 2C", 65, 1540, 660, 70, color=m.GRAY, size=22)
p.e("arrive", "context"); p.e("context", "produce"); p.e("produce", "sealed", "块就绪事件")
p.e("sealed", "register", "是"); p.e("register", "tiers")
p.e("sealed", "produce", "否：\n继续生成", out=(0, .5), into=(0, .5), points=((90, 987), (90, 702)), dashed=True, label_pos=(75, 795, 95, 80))
p.e("produce", "end", "结束\n事件", out=(0, .7), into=(0, .5), points=((20, 727), (20, 1575)), color=m.GRAY, label_pos=(0, 1360, 70, 75))

p.n(1, "frontier", "读取本池 C，找当前连续前缀 f\n已有副本直接复用，不重复计 bytes\n从首缺口枚举已生成的连续候选组 X", 235, 150)
p.d(1, "eligible", "许可 / pending / 回收门槛通过？\n源、时限、staging 和物理容量\n允许复制当前 X？", 475, 210)
p.n(1, "gain", "计算当前保护收益\nA(X|C,t) = Φ(C,t) − Φ(C∪X,t)\n解释其单位字节价值：P = A / b(X)", 790, 145, color=m.PURPLE)
p.n(1, "victims", "若需要空间：按当前损失 / bytes\n选择合法删除闭包 Y，逐轮重算\n禁止删候选祖先和正在读取的对象", 1025, 145)
p.d(1, "improves", "所有候选比较后，有计划满足\nΦ(C,t)−Φ((C\\Y)∪X,t)>η\n且 begin 再校验通过？", 1240, 200)
p.box("pause", "无可行组：PAUSED\n推理继续；新事件后重试\n不永久封死后续 chunk", 850, 1495, 325, 115, color=m.AMBER, size=23)
p.box("commit", "预留 / PENDING → 逐批复制\nACK 齐全且再校验：提交\n失败保留旧 C；回收见 2C", 1220, 1495, 325, 115, color=m.GREEN, size=23)
p.e("tiers", "frontier", out=(1, .5), into=(0, .5), points=((790, 1460), (790, 310)))
p.e("frontier", "eligible"); p.e("eligible", "gain", "是")
p.e("eligible", "pause", "无可行\n候选", out=(0, .5), into=(0, .5), points=((835, 580), (835, 1552)), color=m.AMBER, label_pos=(800, 1115, 85, 80))
p.e("gain", "victims"); p.e("victims", "improves")
p.e("improves", "pause", "否", out=(.25, .75), color=m.AMBER)
p.e("improves", "commit", "是", out=(.75, .75), color=m.GREEN)

p.n(2, "priority", "建议的 Priority：每字节可减少多少\n超出 Slack 的恢复损失\n\nΦ(C,t) = Σ活跃调用 wi [Ti(fi(C),t)−si(t)]₊\nPadd(X|C,t) = [Φ(C,t)−Φ(C∪X,t)] / b(X)\n单 chunk 是 X={k} 的特例", 235, 285, color=m.PURPLE, size=23)
p.n(2, "estimate", "Ti 的来源：按当前生成进度估计\n读取 + 剩余重算 + 输出重放\n在可行前缀与完整重算中取最小代价\n\n需用实测 / 校准模型提供参数；\n参考模块不会自动测出这些数值。", 625, 255, color=m.BLUE, size=23)
p.n(2, "credit", "若另行选择历史租金 Credit：\n插入时 Hk = Lins + Pk\n初始总 Credit = bk · Pk\n剩余 Credit = bk · max(Hk − L, 0)\n\nH 是阈值，L 是本池累计压力租金；\nCredit 与插入 Priority 不同。", 980, 285, color=m.AMBER, size=23)
p.n(2, "open", "Credit 方案仍需明确的规则\n① 压力何时推进 L，失败如何处理\n② Slack / 共享引用变化如何重估或续额\n③ 前缀删除闭包的重叠价值如何处理\n\nCredit=0 只能成为候选；\n仍须验证完整替换的真实收益和安全性。", 1350, 250, color=m.GRAY, size=23)
p.foot("当前推荐：以当前边际收益和完整替换净收益决定备份；如保留历史 Credit，应先定义刷新与租金规则，再作为独立策略验证。",
       "依据：prefix_frontier.py / revision_runtime.py；旧版 rental_value.py；Credit 数学关系见同目录 README")

src = b.save()
for fmt in ("pdf", "png"):
    extra = ["-a", "--crop"] if fmt == "pdf" else ["-s", "1.25"]
    subprocess.run([m.CLI, "-x", "-f", fmt, "-e", "-b", "0", *extra,
                    "-o", str(src) + "." + fmt, str(src)], check=True)

import pymupdf
from PIL import Image
import xml.etree.ElementTree as ET
with pymupdf.open(str(src) + ".pdf") as d:
    assert len(d) == 1 and "算法" in d[0].get_text()
    raw = unquote(d.metadata["subject"])
    if raw != src.read_text():
        assert raw.replace("\\(", "(").replace("\\)", ")") == src.read_text()
        metadata = {k: v for k, v in d.metadata.items() if k not in {"format", "encryption"}}
        metadata["subject"] = quote(src.read_text(), safe="")
        metadata["title"] = "AegisKV request lifecycle and Priority/Credit discussion"
        d.set_metadata(metadata)
        d.saveIncr()
    assert unquote(d.metadata["subject"]) == src.read_text()
    assert all(d[0].rect.contains(pymupdf.Rect(block[:4])) for block in d[0].get_text("blocks"))
with Image.open(str(src) + ".png") as im:
    embedded = ET.fromstring(unquote(im.info["mxGraphModel"]))
    assert [x.get("id") for x in embedded.findall("diagram")] == ["R"]
digest = lambda f: hashlib.sha256(f.read_bytes()).hexdigest()
repo = OUT.parents[4]
inputs = [repo / "python/moonkvsim/aegiskv" / f for f in
          ("prefix_frontier.py", "revision_runtime.py", "rental_value.py")]
record = {"scope": "Request lifecycle of revision 3, plus explicitly unadopted historical Credit option",
          "algorithm_changed": False, "historical_credit_adopted": False,
          "source_sha256": {str(f.relative_to(repo)): digest(f) for f in inputs},
          "generator_sha256": {str(f.relative_to(repo)): digest(f) for f in (BASE, Path(__file__))},
          "output_sha256": {f.name: digest(f) for f in OUT.iterdir() if f.suffix in {".drawio", ".png", ".pdf"}},
          "xml_and_export_checks": "PASS", "visual_review": "PENDING"}
(OUT / "MANIFEST.json").write_text(json.dumps(record, indent=2, ensure_ascii=False) + "\n")
print("Request lifecycle source, PNG and PDF exported and checked")
