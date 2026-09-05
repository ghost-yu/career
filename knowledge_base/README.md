# 本地知识库（可随项目一并提交）

本目录用于存放**可离线检索**的职业规划知识资料，便于在生成“行动计划/学习路径/资源推荐”时做到：
- 可解释（引用到具体资料条目）
- 可更新（学校/企业可持续补充）
- 可离线（不依赖外部爬虫/第三方平台）

## 推荐结构

- `resources/`：Markdown 资料（建议每个技能/主题一个文件）
- `templates/`：行动计划模板（JSON/YAML），如项目模板、实习 checklist、面试 checklist

## 如何构建索引

后端提供：
- `POST /kb/rebuild`：扫描本目录并构建本地 TF-IDF 索引（默认保存到 `backend/data/kb_vectors.pkl`）
- `GET /kb/search?q=Kafka&top_k=5`：检索条目

也可创建异步任务：
- `POST /kb/rebuild_task`

> 你们接入企业真实资料时，可把资料脱敏后放入本目录。
