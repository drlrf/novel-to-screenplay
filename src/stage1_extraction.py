"""Stage 1: 叙事提取 — 角色、场景、对白

将小说文本分解为结构化叙事元素：
1. 角色提取 → 识别所有人物及其特征
2. 场景识别 → 定位场景边界与环境信息
3. 对白提取 → 抽取对话文本并归属角色

跨 chunk 聚合策略：
- 角色：精确名匹配 + fuzzy 匹配 + LLM 确认合并
- 场景：按原文位置排序，相邻 chunk 边界场景合并
- 对白：按 sequence_index 全局编号
"""

import json
import asyncio
import difflib
from dataclasses import dataclass, field, asdict
from typing import Optional

from .exceptions import LLMError
from .chunker import TextChunk
from .prompt_registry import (
    CHARACTER_EXTRACTION_PROMPT,
    SCENE_IDENTIFICATION_PROMPT,
    DIALOGUE_EXTRACTION_PROMPT,
)


# ============================================================
# 数据模型
# ============================================================

@dataclass
class Character:
    """角色"""
    id: str                     # char_001, char_002...
    name: str                   # 角色名
    description: str = ""       # 外貌/身份描述
    traits: list[str] = field(default_factory=list)    # 性格特征
    voice_notes: str = ""       # 台词风格
    importance: str = "major"   # major | minor


@dataclass
class Scene:
    """场景"""
    scene_index: int            # 场景序号
    context: str = "INT."       # INT. | EXT. | INT./EXT.
    location: str = ""          # 地点
    time: str = "DAY"           # DAY | NIGHT | DAWN | DUSK | CONTINUOUS
    actions: list[str] = field(default_factory=list)   # 动作描述列表


@dataclass
class Dialogue:
    """对白"""
    sequence_index: int         # 全局序号
    character_name: str = ""    # 说话角色
    text: str = ""              # 对白内容
    parenthetical: Optional[str] = None  # 表演指示
    context_before: str = ""    # 对白前的叙述


@dataclass
class NarrativeData:
    """Stage 1 完整输出"""
    characters: list[Character] = field(default_factory=list)
    scenes: list[Scene] = field(default_factory=list)
    dialogues: list[Dialogue] = field(default_factory=list)

    def to_dict(self) -> dict:
        """序列化为 dict，方便存数据库和传给 Stage 2"""
        return {
            "characters": [asdict(c) for c in self.characters],
            "scenes": [asdict(s) for s in self.scenes],
            "dialogues": [asdict(d) for d in self.dialogues],
        }

    @classmethod
    def from_dict(cls, data: dict) -> "NarrativeData":
        """从 dict 反序列化"""
        return cls(
            characters=[Character(**c) for c in data.get("characters", [])],
            scenes=[Scene(**s) for s in data.get("scenes", [])],
            dialogues=[Dialogue(**d) for d in data.get("dialogues", [])],
        )


# ============================================================
# Stage 1 编排器
# ============================================================

class Stage1Extractor:
    """编排 Stage 1 的三个提取步骤"""

    def __init__(self, llm):  # llm: OllamaClient or DeepSeekClient
        self.llm = llm

    async def run(self, chunks: list[TextChunk]) -> NarrativeData:
        """
        对一批 chunk 执行完整 Stage 1 提取

        Args:
            chunks: 一个或多个章节的 TextChunk 列表

        Returns:
            NarrativeData（角色 + 场景 + 对白）
        """
        # 三个步骤顺序执行（Ollama 本地模型不支持并发）
        raw_characters = await self._extract_characters(chunks)
        characters = self._aggregate_characters(raw_characters)

        raw_scenes = await self._extract_scenes(chunks)
        scenes = self._merge_scenes(raw_scenes)

        raw_dialogues = await self._extract_dialogues(chunks, characters)
        dialogues = self._number_dialogues(raw_dialogues)

        # 角色 ID 标准化
        characters = self._assign_character_ids(characters)

        return NarrativeData(
            characters=characters,
            scenes=scenes,
            dialogues=dialogues,
        )

    # ============================================================
    # 角色提取
    # ============================================================

    async def _extract_characters(self, chunks: list[TextChunk]) -> list[dict]:
        """对所有 chunk 并发调 LLM 提取角色"""
        async def extract_one(chunk):
            prompt = CHARACTER_EXTRACTION_PROMPT.format(chapter_text=chunk.text)
            try:
                result = await self.llm.generate_json(prompt)
                chars = result.get("characters", [])
                for c in chars:
                    c["_source_chunk"] = chunk.chunk_index
                return chars
            except LLMError as e:
                print(f"[Stage1] 角色提取失败 (chunk {chunk.chunk_index}): {e}")
                return []

        results = await asyncio.gather(*[extract_one(c) for c in chunks])
        return [c for r in results for c in r]

    def _aggregate_characters(self, raw_chars: list[dict]) -> list[Character]:
        """
        跨 chunk 聚合角色：同名合并 + 模糊匹配 + 去重

        策略：
        1. 精确名字匹配 → 直接合并（取信息最丰富的描述）
        2. 模糊匹配（相似度 > 0.8）→ 合并
        3. 无法匹配 → 新增角色
        """
        merged: list[Character] = []

        for raw in raw_chars:
            name = raw.get("name", "").strip()
            if not name:
                continue

            # 尝试匹配已有角色
            matched = self._find_matching_character(name, merged)

            if matched:
                # 合并：用信息更丰富的版本覆盖
                self._merge_character_info(matched, raw)
            else:
                merged.append(Character(
                    id="",  # ID 稍后统一分配
                    name=name,
                    description=raw.get("description", ""),
                    traits=raw.get("traits", []),
                    voice_notes=raw.get("voice_notes", ""),
                    importance=raw.get("importance", "major"),
                ))

        # 按重要性排序：major 在前
        merged.sort(key=lambda c: (0 if c.importance == "major" else 1, c.name))
        return merged

    def _find_matching_character(self, name: str, existing: list[Character]) -> Optional[Character]:
        """在已有角色列表中查找匹配的角色"""
        for char in existing:
            # 精确匹配
            if char.name == name:
                return char
            # 包含关系（"李明" vs "李明（主角）"）
            if name in char.name or char.name in name:
                return char
            # 模糊匹配
            if difflib.SequenceMatcher(None, char.name, name).ratio() > 0.8:
                return char
        return None

    def _merge_character_info(self, target: Character, source: dict):
        """将 source 的信息合并到 target（保留更丰富的版本）"""
        src_desc = source.get("description", "")
        if src_desc and len(src_desc) > len(target.description):
            target.description = src_desc

        src_traits = source.get("traits", [])
        for t in src_traits:
            if t not in target.traits:
                target.traits.append(t)

        src_voice = source.get("voice_notes", "")
        if src_voice and len(src_voice) > len(target.voice_notes):
            target.voice_notes = src_voice

        # 只要有一个 chunk 标记为 major，就是 major
        if source.get("importance") == "major":
            target.importance = "major"

    def _assign_character_ids(self, characters: list[Character]) -> list[Character]:
        """为角色分配标准化 ID（char_001, char_002...）"""
        for i, char in enumerate(characters):
            char.id = f"char_{i+1:03d}"
        return characters

    # ============================================================
    # 场景提取
    # ============================================================

    async def _extract_scenes(self, chunks: list[TextChunk]) -> list[dict]:
        """对所有 chunk 并发调 LLM 识别场景"""
        async def extract_one(chunk):
            prompt = SCENE_IDENTIFICATION_PROMPT.format(chapter_text=chunk.text)
            try:
                result = await self.llm.generate_json(prompt)
                scenes = result.get("scenes", [])
                for s in scenes:
                    s["_source_chunk"] = chunk.chunk_index
                return scenes
            except LLMError as e:
                print(f"[Stage1] 场景识别失败 (chunk {chunk.chunk_index}): {e}")
                return []

        results = await asyncio.gather(*[extract_one(c) for c in chunks])
        return [s for r in results for s in r]

    def _merge_scenes(self, raw_scenes: list[dict]) -> list[Scene]:
        """
        合并场景：去重 + 全局编号

        相邻 chunk 的 overlap 区域可能识别出同一场景，
        通过 location 和 time 匹配来去重。
        """
        scenes = []
        seen_keys = set()

        for raw in raw_scenes:
            location = raw.get("location", "").strip()
            time = raw.get("time", "DAY").strip()
            # 用 location + time 做去重 key
            key = f"{location}|{time}"

            if key in seen_keys:
                # 同一场景：找到已存在的场景并合并 actions
                existing = next((s for s in scenes if s.location == location and s.time == time), None)
                if existing:
                    new_actions = raw.get("actions", [])
                    for a in new_actions:
                        if a not in existing.actions:
                            existing.actions.append(a)
            else:
                seen_keys.add(key)
                scenes.append(Scene(
                    scene_index=0,  # 稍后重编号
                    context=raw.get("context", "INT."),
                    location=location,
                    time=time,
                    actions=raw.get("actions", []),
                ))

        # 全局编号
        for i, s in enumerate(scenes):
            s.scene_index = i + 1

        return scenes

    # ============================================================
    # 对白提取
    # ============================================================

    async def _extract_dialogues(self, chunks: list[TextChunk], characters: list[Character]) -> list[dict]:
        """对所有 chunk 并发调 LLM 提取对白"""
        char_list_json = json.dumps(
            [{"name": c.name, "id": c.id} for c in characters],
            ensure_ascii=False,
        )

        async def extract_one(chunk):
            prompt = DIALOGUE_EXTRACTION_PROMPT.format(
                chapter_text=chunk.text,
                character_list_json=char_list_json,
            )
            try:
                result = await self.llm.generate_json(prompt)
                dialogues = result.get("dialogues", [])
                for d in dialogues:
                    d["_source_chunk"] = chunk.chunk_index
                return dialogues
            except LLMError as e:
                print(f"[Stage1] 对白提取失败 (chunk {chunk.chunk_index}): {e}")
                return []

        results = await asyncio.gather(*[extract_one(c) for c in chunks])
        return [d for r in results for d in r]

    def _number_dialogues(self, raw_dialogues: list[dict]) -> list[Dialogue]:
        """将对白全局编号并转换为 Dialogue 对象"""
        dialogues = []
        for raw in raw_dialogues:
            dialogues.append(Dialogue(
                sequence_index=0,  # 稍后重编号
                character_name=raw.get("character_name", ""),
                text=raw.get("text", ""),
                parenthetical=raw.get("parenthetical"),
                context_before=raw.get("context_before", ""),
            ))

        for i, d in enumerate(dialogues):
            d.sequence_index = i + 1

        return dialogues
