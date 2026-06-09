# 剧本 YAML Schema 定义与设计理由

## 一、Schema 完整定义

```yaml
# 剧本 YAML Schema v1.0
# 用于将小说文本转换为结构化剧本的中间表示

meta:                          # 元数据
  title: "剧本标题"             # 必填，剧本名称
  author: "原著作者"            # 必填，小说原作者
  adapter: "AI 小说转剧本工具"  # 必填，改编工具标识
  date: "2026-06-05"           # 必填，生成日期 ISO8601
  version: "1.0"               # 必填，Schema 版本号

dramatis_personae:             # 人物表，至少包含 1 个角色
  - id: "char_001"             # 必填，角色唯一标识（全剧本引用）
    name: "角色名"             # 必填
    description: "外貌与身份描述"  # 可选
    traits:                    # 可选，性格特征列表
      - "勇敢"
      - "冲动"
    voice_notes: "台词风格备注"  # 可选（语速、口癖、方言等）

scenes:                        # 场景列表，至少包含 1 个场景
  - scene_number: 1            # 必填，场景序号（从 1 开始递增）
    heading:                   # 必填，场景标题
      context: "INT."          # 必填，INT. | EXT. | INT./EXT.
      location: "地点描述"     # 必填
      time: "NIGHT"            # 必填，DAY | NIGHT | DAWN | DUSK | CONTINUOUS
    action:                    # 可选，场景动作描述
      - text: "环境与动作描写"
    elements:                  # 必填，场景内元素有序列表
      - type: "character"      # 元素类型：character
        character_id: "char_001"  # 引用 dramatis_personae 中的 id
      - type: "parenthetical"  # 元素类型：parenthetical（括号表演指示）
        text: "（低声地）"
      - type: "dialogue"       # 元素类型：dialogue（对白）
        text: "对白内容"
      - type: "transition"     # 元素类型：transition（转场标记）
        text: "CUT TO:"
    transition: "CUT TO:"      # 可选，场景结尾转场
```

### 元素类型枚举

| type | 说明 | 必需前置元素 | 特有字段 |
|------|------|-------------|---------|
| `character` | 说话角色 | 无 | `character_id` |
| `parenthetical` | 表演指示 | `character` | `text` |
| `dialogue` | 对白文本 | `character` 或 `parenthetical` | `text` |
| `transition` | 转场标记 | `dialogue` 或 `action` | `text` |

### 元素排列规则

```
[action] → [character] → [parenthetical?] → [dialogue] → [transition?] → [action] → ...
```

- `dialogue` 前面必须有 `character`，中间最多隔一个 `parenthetical`
- `parenthetical` 必须在 `character` 和 `dialogue` 之间
- 相邻两个 `character` 元素之间必须有一个 `dialogue`

---

## 二、设计理由

### 2.1 为什么选择 YAML 而不是 Fountain 纯文本？

| 维度 | YAML | Fountain |
|------|------|----------|
| 结构化程度 | 高（嵌套、类型明确） | 低（依赖缩进和标记符） |
| 程序化处理 | 原生支持（任意语言解析） | 需要专用解析器 |
| 可扩展性 | 加字段即可 | 需要新语法约定 |
| 人类可读 | 良好 | 极佳 |
| 与 LLM 兼容 | JSON 近亲，LLM 易生成 | 自由文本，LLM 易偏离格式 |

**结论：** 剧本格式选 YAML，中间生成用 JSON（更严格），最终输出转 YAML（人类可读）。不选 Fountain 是因为解析器生态太窄，且 LLM 生成自由格式文本时容易偏离格式规范。

### 2.2 为什么用 elements 数组而不是平铺文本？

elements 数组将场景内容拆分为类型化元素序列，这样做的好处：

1. **可量化分析**：统计每个角色的台词数量、场景分布
2. **可二次加工**：提取纯对话、纯动作描述、仅角色列表
3. **格式校验**：自动检测元素排序错误（如 dialogue 前没有 character）
4. **角色追溯**：每条对白通过 `character_id` 精确关联到角色表

平铺文本虽然更接近"人读的剧本"，但对机器处理和校验不友好。

### 2.3 为什么有独立的 dramatis_personae（人物表）？

- **去重**：同一个角色出现在多个场景，通过 `character_id` 引用而非重复描述
- **一致性**：角色信息集中管理，避免场景间角色描述矛盾
- **可扩展**：后续可加角色弧线、关系图谱等字段

### 2.4 为什么用 JSON 作为 LLM 输出而非直接生成 YAML？

1. **YAML 对缩进敏感**：LLM 生成的 YAML 常因空格数量错误而无法解析
2. **JSON 的语法更严格**：花括号和引号比缩进更难出错
3. **Ollama 支持 JSON mode**：可通过 `format: json` 参数约束输出
4. **Python 转换可靠**：`json.dumps()` → `ruamel.yaml` 是确定性转换，不出错

### 2.5 与现有格式的对比

| 特性 | 本 Schema | ScreenJSON | Fountain | Final Draft XML |
|------|----------|------------|----------|-----------------|
| 格式 | YAML | JSON | 纯文本 | XML |
| 角色引用 | id 引用 | UUID 引用 | 纯文本 | Paragraph 属性 |
| 复杂度 | 中等（够用） | 高（生产级） | 低 | 高 |
| LLM 生成友好度 | 高（JSON 中间层） | 中（字段多） | 低（易偏离） | 低（标签嵌套深） |
| 场景分析 | 原生支持 | 原生支持 | 需解析 | 原生支持 |

本 Schema 的设计哲学是 **"够用、可扩展、LLM 友好"**，不做 ScreenJSON 那样的全量生产格式（含机位、道具清单等），聚焦于小说→剧本这个特定转换场景的核心需求。

---

## 三、扩展预留

未来版本可增补的字段（当前 Schema 已预留空间）：

- `meta.target_audience` — 目标受众
- `dramatis_personae[].arc` — 角色弧线描述
- `scenes[].elements[].camera` — 机位建议
- `scenes[].estimated_duration` — 预估时长
- `end_matter` — 批注、改编说明等尾注
