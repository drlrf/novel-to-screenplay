# AI 小说转剧本工具

将小说文本（3 章以上）自动转换为结构化剧本（YAML 格式），帮助作者快速获得可编辑、可进一步打磨的剧本初稿。

demo 视频：<待补充>

## 技术栈

| 层级 | 技术 |
|------|------|
| 后端框架 | FastAPI |
| AI 模型 | DeepSeek API（deepseek-v4-flash）/ Ollama（本地） |
| 数据库 | SQLite |
| 前端 | 原生 HTML/CSS/JS |
| YAML | ruamel.yaml |
| 文本解析 | pdfplumber / ebooklib + BeautifulSoup |

## 快速启动

```bash
# 1. 安装依赖
pip install fastapi uvicorn httpx ruamel.yaml ebooklib beautifulsoup4

# 2. 配置 API Key（如使用 DeepSeek）
# 编辑 src/config.py，将 DEEPSEEK_API_KEY 设为你的 Key

# 3. 启动服务
cd novel-to-screenplay
uvicorn src.main:app --reload

# 4. 访问
# 前端界面: http://localhost:8000
# API 文档: http://localhost:8000/docs
```

## 模型切换

编辑 `src/config.py`：

```python
LLM_BACKEND = "deepseek"   # 使用 DeepSeek API（推荐，速度快）
LLM_BACKEND = "ollama"     # 使用本地 Ollama（离线可用）
```

| 后端 | 速度 | 质量 | 成本 | 需要 |
|------|:--:|:--:|:--:|------|
| DeepSeek API | 快（~40s/3章） | 高 | 约 ¥0.01/次 | 网络 + API Key |
| Ollama 本地 | 慢（~3min/3章） | 中 | 免费 | 本地模型文件 |

## 支持的文件格式

| 格式 | 支持情况 | 推荐度 | 说明 |
|------|:--:|:--:|------|
| .txt | ✅ | ⭐⭐⭐⭐ | 需含"第X章"等章节标记，UTF-8/GBK 编码均可 |
| .epub | ✅ | ⭐⭐⭐⭐⭐ | 推荐，章节结构天然在 EPUB 内，自动过滤版权页 |
| .pdf | 待支持 | — | 可通过 pdfplumber 扩展 |

### 上传文件建议

1. **章节结构清晰**：最好有"第X章""Chapter N"等明确标记。无标记的意识流小说（如《活着》）会被均分，效果打折
2. **每章建议 1000~3000 字**：太短对白少，太长转换慢
3. **EPUB 优于 TXT**：EPUB 的章节结构能直接利用，更准确

## 工作流程

```
上传文件 → 自动分章 → 选择章节 → 
  Stage 1（叙事提取）→ Stage 2（格式转换+校验修复）→ YAML 输出
```

### 核心技术架构

- **两阶段流水线**：叙事提取与格式转换分离，Prompt 各司其职
- **JSON 中间层**：LLM 生成 JSON → Python 代码转 YAML，避免 LLM 直接生成 YAML 的格式错误
- **验证-修复循环**：Schema 校验 → 错误反馈 → LLM 修复 → 再校验（最多 3 轮）
- **跨块并发 + 聚合去重**：长文本分块后并发提取，角色信息跨块合并

## 项目结构

```
novel-to-screenplay/
├── README.md
├── SCHEMA.md                  # YAML Schema 定义与设计理由
├── data/                      # 测试数据
├── src/
│   ├── main.py                # FastAPI 入口（15 个 API 端点）
│   ├── config.py              # 配置（模型、后端、参数）
│   ├── db.py                  # SQLite 数据库
│   ├── llm_client.py          # Ollama 客户端
│   ├── deepseek_client.py     # DeepSeek API 客户端
│   ├── prompt_registry.py     # 5 个 Prompt 模板
│   ├── novel_ingestion.py     # 文件上传、清洗、分章、EPUB 解析
│   ├── chunker.py             # 段落感知文本分块
│   ├── stage1_extraction.py   # Stage 1: 角色/场景/对白提取 + 并发 + 聚合
│   ├── stage2_conversion.py   # Stage 2: 剧本 JSON 组装
│   ├── schema_validator.py    # JSON Schema 校验（9 类规则）
│   ├── validate_repair.py     # 验证-修复循环（最多 3 轮）
│   └── yaml_converter.py      # JSON → YAML 确定性转换
└── static/
    ├── index.html             # 单页界面
    └── app.js                 # 上传/轮询/预览/下载

```

## 依赖说明

| 库 | 用途 | 是否原创替代 |
|----|------|-------------|
| fastapi / uvicorn | Web 框架与服务器 | - |
| httpx | 异步 HTTP 客户端 | - |
| ruamel.yaml | YAML 序列化（保留 key 顺序） | - |
| ebooklib + BeautifulSoup | EPUB 解析与 HTML 文本提取 | - |
| sqlite3 | 数据库（Python 内置） | - |

核心功能（Prompt 工程、Stage 1/2 流水线、Schema 校验规则、验证-修复循环、跨块并发与聚合去重、EPUB 结构解析、注释/版权过滤）均为原创实现。
