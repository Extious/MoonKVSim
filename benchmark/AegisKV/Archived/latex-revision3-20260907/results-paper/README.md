# 论文数据与构建产物

- `data/`：统计、绘图输入、来源绑定、原始 Motivation 重建与交付检查。
- `build/`：LaTeX 辅助文件、构建日志及中间 PDF。
- `review/`：当前 PDF 页面渲染和版面检查记录。
- `delivery/`：论文源码、可编辑图像、冻结模拟代码包与校验清单。
- `source-bundle-check/`：独立解包、编译与图像重建的临时工作树。
- `archive-build-before/`：整理前的编译缓存与补充来源文件。
- `REORGANIZATION.json`：原位置、新位置与迁移前 SHA-256。

论文入口：[paper/README.md](../../../paper/README.md)。
实验的冻结源码及完整原始事件仍保留在仓库 `output/paper-simulation-8b/`。

算法 2/3 revision 3 的新验证位于相邻 `algorithm-revision-v3/`。`delivery/` 中旧包已经标注为历史版本；其 PASS 不适用于当前 PDF。
