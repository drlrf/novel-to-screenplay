"""Stage 2: 格式转换 — NarrativeData → 剧本 JSON → YAML

编排流程：
1. 将 NarrativeData 组装为 LLM 的输入（JSON 格式的角色表/场景表/对白表）
2. 调 LLM 生成符合 Schema 的完整剧本 JSON
3. 验证-修复循环
4. JSON → YAML 输出
"""

import json
from datetime import datetime, timezone

from .llm_client import OllamaClient, LLMError
from .stage1_extraction import NarrativeData
from .schema_validator import ScreenplayValidator
from .validate_repair import RepairLoop, RepairFailedError
from .yaml_converter import dict_to_yaml
from .prompt_registry import SCENE_ASSEMBLY_PROMPT


class Stage2Converter:
    """编排 Stage 2 转换流程"""

    def __init__(self, llm: OllamaClient):
        self.llm = llm
        self.repair = RepairLoop(llm)

    async def convert(self, narrative: NarrativeData, meta: dict | None = None) -> dict:
        """
        将 NarrativeData 转换为最终剧本 YAML

        Args:
            narrative: Stage 1 提取的叙事数据
            meta: 自定义元数据（title、author），不传则用默认值

        Returns:
            {"yaml": str, "json": dict, "repair_log": [...]}
        """
        meta = meta or {}
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

        # 1. 组装角色表 JSON
        dramatis_personae = []
        for char in narrative.characters:
            dramatis_personae.append({
                "id": char.id,
                "name": char.name,
                "description": char.description,
                "traits": char.traits,
                "voice_notes": char.voice_notes,
            })

        # 2. 组装场景表 JSON
        scenes_data = []
        for scene in narrative.scenes:
            scenes_data.append({
                "scene_index": scene.scene_index,
                "context": scene.context,
                "location": scene.location,
                "time": scene.time,
                "actions": scene.actions,
            })

        # 3. 组装对白表 JSON
        dialogues_data = []
        for dialogue in narrative.dialogues:
            dialogues_data.append({
                "sequence_index": dialogue.sequence_index,
                "character_name": dialogue.character_name,
                "text": dialogue.text,
                "parenthetical": dialogue.parenthetical,
                "context_before": dialogue.context_before,
            })

        # 4. 构造 Assembly Prompt
        prompt = SCENE_ASSEMBLY_PROMPT.format(
            dramatis_personae_json=json.dumps(dramatis_personae, ensure_ascii=False, indent=2),
            scenes_json=json.dumps(scenes_data, ensure_ascii=False, indent=2),
            dialogues_json=json.dumps(dialogues_data, ensure_ascii=False, indent=2),
        )

        # 5. 调 LLM 生成剧本 JSON
        print("[Stage2] 调用 LLM 组装剧本 JSON...")
        try:
            screenplay_json = await self.llm.generate_json(prompt)
        except LLMError as e:
            raise RuntimeError(f"Stage 2 LLM 调用失败: {e}")

        # 6. 填入 meta 信息（LLM 可能编造日期，用真实值覆盖）
        screenplay_json["meta"]["title"] = meta.get("title", screenplay_json.get("meta", {}).get("title", "未命名"))
        screenplay_json["meta"]["author"] = meta.get("author", screenplay_json.get("meta", {}).get("author", "佚名"))
        screenplay_json["meta"]["date"] = today
        screenplay_json["meta"]["adapter"] = "AI 小说转剧本工具"
        screenplay_json["meta"]["version"] = "1.0"

        # 7. 验证-修复循环
        print("[Stage2] 开始验证-修复循环...")
        try:
            valid_json, repair_log = await self.repair.repair(screenplay_json)
        except RepairFailedError as e:
            # 修复失败但仍返回当前版本（带错误标注）
            print(f"[Stage2] {e}")
            valid_json = screenplay_json
            valid_json["_repair_failed"] = True
            valid_json["_remaining_errors"] = str(e)
            repair_log = []

        # 8. JSON → YAML
        yaml_str = dict_to_yaml(valid_json)

        return {
            "yaml": yaml_str,
            "json": valid_json,
            "repair_log": repair_log,
        }
