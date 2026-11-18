# 新增论文首页身份核对

日期：2026-10-03。PyMuPDF 在 140 DPI 渲染 15 篇新增 PDF 的第一页，结合首两页可提取文本及原始来源核对。已查看 contact-1.png、contact-2.png、contact-3.png 三张联系表，覆盖 HiSparse、SPIN、SAC、PBKV、TokenCake、CacheWise、GraphFlow、LMCache、CachedAttention、InfiniGen、NOSA、Parrot、OrbitFlow、PagedAttention、MemServe。

- 标题、作者区、论文内容可见，无下载错误页或空白首页。
- OrbitFlow 没有嵌入 arXiv 水印；以固定版本请求/响应 URL、匹配题名及首页 PVLDB DOI 核验，已记录在 SOURCES.json 和 VALIDATION.json。
- MemServe v3 的 PDF 题名与 arXiv HTML/Consensus 旧题名不同。引用采用 PDF 题名，保留旧文件名/检索题名作为别名，不重复计数。
- LMCache v2 首页前三位作者顺序与 arXiv HTML 元数据不同；以 PDF 顺序生成引用，保留原元数据。
- TokenCake、NOSA、GraphFlow 首页的会议/接收文字未一概升级为本次已核验的正式出版记录。

范围限制：只核对首页视觉身份与必要元数据；没有逐页视觉审查、字体合规/无障碍检查或论文实验复现。整篇结构与文本提取检查由 validate.py 完成，没有修改任何论文 PDF。
