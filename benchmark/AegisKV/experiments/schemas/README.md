# AegisKV JSON schemas

本目录保存 AegisKV 专用配置和结果格式约束。2026-10-04 从仓库根目录
`schemas/aegiskv-*.schema.json` 迁入；schema 名称和 `$id` 保持原值。

仓库级 `moonkvsim.config.validation.load_schema` 将已注册的 AegisKV 故障 schema
路由到本目录，通用 MoonKVSim schema 继续从根目录 `schemas/` 加载。
Qwen3-32B 配置、Qwen3-8B 验收及历史无故障开销 runner 的专用加载路径也已更新。

无故障开销 schema 接受新的规范路径，以及历史结果 provenance 中的
`schemas/aegiskv-no-failure-overhead.schema.json`。历史结果不因目录整理而重写，
新的 runner 记录本目录路径及当前文件哈希。

迁移前后逐文件哈希和代码路径调整见
[整理记录](../../exports/project-cleanup-20261004/README.md)。
