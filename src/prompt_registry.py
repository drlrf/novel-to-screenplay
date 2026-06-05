"""Prompt 模板集中管理

每个 Prompt 遵循 5 段式结构：
1. 角色定位（一句话）
2. 任务定义（编号列表）
3. 输出格式（JSON 示例）
4. 输入数据占位符（{xxx}）
5. 收尾约束（重复强调 JSON 输出）

占位符说明：
- {chapter_text} — 小说片段文本
- {character_list_json} — 已知角色列表的 JSON 字符串
- {dramatis_personae_json} — 人物表的 JSON 字符串
- {scenes_json} — 场景列表的 JSON 字符串
- {dialogues_json} — 对白列表的 JSON 字符串
- {error_list_formatted} — 校验错误列表的格式化文本
- {invalid_json} — 待修复的 JSON 字符串
"""

# ================================================================
# Stage 1: 叙事提取
# ================================================================

CHARACTER_EXTRACTION_PROMPT = """你是一位专业的剧本分析师。请仔细阅读以下小说片段，完成角色提取任务。

## 任务
1. 识别出片段中出现的所有角色（包括被提及但未直接出场的角色）
2. 对每个角色，提取以下信息：
   - 姓名（中文全名，如有别名也列出来）
   - 外貌与身份描述（简练，1-2句话）
   - 性格特征（3-5个关键词或短语）
   - 台词风格备注（语速快慢、口头禅、方言、说话习惯等）
3. 区分"主要角色"（有台词或有重要行动）和"次要角色"（仅被提及或背景角色）

## 输出格式（严格JSON，不要输出其他内容）
{{
  "characters": [
    {{
      "name": "角色名",
      "description": "外貌与身份描述",
      "traits": ["特征1", "特征2"],
      "voice_notes": "台词风格备注",
      "importance": "major"
    }}
  ]
}}

importance 取值为 "major" 或 "minor"。

## 小说片段
{chapter_text}

请先逐步分析片段中出现了哪些人物，他们各自做了什么、说了什么，然后输出严格JSON。"""


SCENE_IDENTIFICATION_PROMPT = """你是一位经验丰富的分镜师。请分析以下小说片段，识别场景边界并提取场景信息。

## 场景切换的判断标准
以下任何一种情况发生，即为新场景：
- 地点发生变化（室内→室外、不同房间、不同建筑）
- 时间发生明显跳跃（白天→夜晚、"几天后"、"与此同时"）
- 视角切换到另一组角色群体

## 任务
1. 识别片段中所有场景边界，标注场景的起始位置
2. 对每个场景，提取：
   - context：INT.（内景）、EXT.（外景）或 INT./EXT.（内外景都有）
   - location：地点描述（如"李明的公寓客厅"）
   - time：DAY / NIGHT / DAWN / DUSK / CONTINUOUS（与前一个场景连续）
3. 提取每个场景中的动作描述（环境描写、角色行为等）

## 输出格式（严格JSON，不要输出其他内容）
{{
  "scenes": [
    {{
      "scene_index": 0,
      "context": "INT.",
      "location": "地点描述",
      "time": "NIGHT",
      "actions": ["动作描述段落1", "动作描述段落2"]
    }}
  ]
}}

context 取值：INT. / EXT. / INT./EXT.
time 取值：DAY / NIGHT / DAWN / DUSK / CONTINUOUS

## 小说片段
{chapter_text}

请先逐步分析场景变化节点，然后输出严格JSON。"""


DIALOGUE_EXTRACTION_PROMPT = """你是一位对话编剧。请从以下小说片段中提取所有角色对白。

## 已知角色列表
{character_list_json}

## 任务
1. 提取片段中所有对白（包括直接对话和独白）
2. 将每句对白归属到正确的角色（使用角色列表中已有的角色名）
3. 识别台词前的表演指示（如"（低声）"、"（愤怒地）"、"（停顿）"等），记录为 parenthetical
4. 对白中出现的新角色（不在已知角色列表中），在 new_characters 中列出
5. 保持对白在原文中的出现顺序

## 输出格式（严格JSON，不要输出其他内容）
{{
  "dialogues": [
    {{
      "sequence_index": 0,
      "character_name": "角色名",
      "text": "对白文本（不含引号，纯台词）",
      "parenthetical": null,
      "context_before": "该对白之前的动作或叙述（可选）"
    }}
  ],
  "new_characters": [
    {{
      "name": "新角色名",
      "description": "简要描述",
      "traits": [],
      "voice_notes": ""
    }}
  ]
}}

parenthetical 示例：（低声）、（停顿）、（愤怒地）、（对观众）
如果该对白没有 parenthetical，则为 null。

## 小说片段
{chapter_text}

请先逐段分析对话部分，确认每句话由谁说、怎么说，然后输出严格JSON。"""


# ================================================================
# Stage 2: 格式转换
# ================================================================

SCENE_ASSEMBLY_PROMPT = """你是一位剧本格式化专家。请将以下已提取的叙事元素，按标准剧本格式组成为完整的场景JSON。

## 剧本格式规则
1. 场景元素（elements）排列顺序：action → character → parenthetical(可选) → dialogue → transition(可选) → 重复
2. 每个场景开头至少有一段 action（环境/动作描述）
3. dialogue 前面必须有 character 元素，中间最多隔一个 parenthetical
4. 所有角色引用必须使用 dramatis_personae 中定义的 id（char_001、char_002...）
5. 对话文本用原对白内容，必要时微调使其更口语化
6. 每个场景以 transition 结尾

## 输入数据

### 人物表
{dramatis_personae_json}

### 场景列表
{scenes_json}

### 对白列表
{dialogues_json}

## 输出格式（严格JSON，不要输出其他内容）
{{
  "meta": {{
    "title": "剧本标题",
    "author": "原著作者",
    "adapter": "AI 小说转剧本工具",
    "date": "当前日期",
    "version": "1.0"
  }},
  "dramatis_personae": [
    {{
      "id": "char_001",
      "name": "角色名",
      "description": "外貌与身份描述",
      "traits": ["特征"],
      "voice_notes": "台词风格"
    }}
  ],
  "scenes": [
    {{
      "scene_number": 1,
      "heading": {{
        "context": "INT.",
        "location": "地点",
        "time": "NIGHT"
      }},
      "action": [
        {{"text": "动作描述"}}
      ],
      "elements": [
        {{"type": "character", "character_id": "char_001"}},
        {{"type": "parenthetical", "text": "（低声）"}},
        {{"type": "dialogue", "text": "对白内容"}},
        {{"type": "transition", "text": "CUT TO:"}}
      ],
      "transition": "CUT TO:"
    }}
  ]
}}

## 重要提示
- 请确保所有字符串正确转义（内部的双引号用 \\\" 转义）
- 确保 dramatis_personae 中的 id 在 scenes 中被正确引用
- elements 数组必须遵循 character → parenthetical → dialogue 的顺序约束

请先整理数据对应关系，确认角色、场景、对白的匹配，然后输出严格JSON。"""


# ================================================================
# 修复
# ================================================================

REPAIR_PROMPT = """你是一位JSON修复专家。以下剧本JSON在格式校验时发现了错误，请修复这些错误。

## 校验发现的错误
{error_list_formatted}

## 需要修复的JSON
```json
{invalid_json}
```

## 修复要求
1. 只修复上面列出的错误，不要修改其他内容
2. 如果错误涉及 character_id 引用不存在的角色，删除无效引用或替换为正确的 id
3. 确保 elements 数组遵循 character → parenthetical(可选) → dialogue 的元素顺序
4. 确保所有必需字段存在且类型正确
5. 输出修复后的完整 JSON，不要省略任何字段

请分析每个错误的原因，逐条修复，然后输出完整的修复后JSON。"""
