"""剧本 JSON Schema 校验器

按 YAML Schema 定义逐条校验 LLM 生成的剧本 JSON，
返回结构化的错误列表供修复循环使用。
"""

from dataclasses import dataclass


# ============================================================
# 数据模型
# ============================================================

@dataclass
class ValidationError:
    """单条校验错误"""
    field: str       # 出错字段路径，如 "scenes[0].heading.context"
    message: str     # 人类可读的错误描述


# ============================================================
# 常量定义
# ============================================================

VALID_CONTEXTS = {"INT.", "EXT.", "INT./EXT."}
VALID_TIMES = {"DAY", "NIGHT", "DAWN", "DUSK", "CONTINUOUS"}
VALID_ELEMENT_TYPES = {"character", "parenthetical", "dialogue", "transition"}
REQUIRED_META_FIELDS = {"title", "author", "adapter", "date", "version"}
REQUIRED_CHARACTER_FIELDS = {"id", "name"}
REQUIRED_SCENE_FIELDS = {"scene_number", "heading", "elements"}
REQUIRED_HEADING_FIELDS = {"context", "location", "time"}


# ============================================================
# 校验器
# ============================================================

class ScreenplayValidator:
    """剧本 JSON 结构校验器"""

    def validate(self, screenplay: dict) -> list[ValidationError]:
        """
        对剧本 JSON 执行完整校验

        Args:
            screenplay: Stage 2 生成的完整剧本 JSON

        Returns:
            错误列表，为空表示通过
        """
        errors = []

        # 1. 顶层结构
        if not isinstance(screenplay, dict):
            return [ValidationError("root", "剧本 JSON 必须是一个对象")]

        # 2. meta
        errors.extend(self._validate_meta(screenplay.get("meta", {})))

        # 3. dramatis_personae
        errors.extend(self._validate_characters(screenplay.get("dramatis_personae", [])))
        valid_ids = self._collect_character_ids(screenplay.get("dramatis_personae", []))

        # 4. scenes
        errors.extend(self._validate_scenes(screenplay.get("scenes", []), valid_ids))

        return errors

    # ============================================================
    # meta 校验
    # ============================================================

    def _validate_meta(self, meta: dict) -> list[ValidationError]:
        errors = []
        for field in REQUIRED_META_FIELDS:
            if field not in meta:
                errors.append(ValidationError(f"meta.{field}", f"缺少必填字段 '{field}'"))
            elif not isinstance(meta[field], str):
                errors.append(ValidationError(f"meta.{field}", f"字段类型应为字符串，实际为 {type(meta[field]).__name__}"))
        return errors

    # ============================================================
    # dramatis_personae 校验
    # ============================================================

    def _validate_characters(self, characters: list) -> list[ValidationError]:
        errors = []
        if not isinstance(characters, list):
            return [ValidationError("dramatis_personae", "必须是一个数组")]
        if len(characters) == 0:
            errors.append(ValidationError("dramatis_personae", "角色列表不能为空"))
            return errors

        seen_ids = set()
        for i, char in enumerate(characters):
            prefix = f"dramatis_personae[{i}]"

            if not isinstance(char, dict):
                errors.append(ValidationError(prefix, "角色必须是一个对象"))
                continue

            # 必填字段
            for field in REQUIRED_CHARACTER_FIELDS:
                if field not in char:
                    errors.append(ValidationError(f"{prefix}.{field}", f"缺少必填字段 '{field}'"))

            # id 唯一性
            char_id = char.get("id", "")
            if char_id in seen_ids:
                errors.append(ValidationError(f"{prefix}.id", f"角色 id '{char_id}' 重复"))
            seen_ids.add(char_id)

            # 字段类型
            if "traits" in char and not isinstance(char["traits"], list):
                errors.append(ValidationError(f"{prefix}.traits", "traits 必须是字符串数组"))

        return errors

    def _collect_character_ids(self, characters: list) -> set[str]:
        """收集所有有效的角色 id"""
        return {c["id"] for c in characters if isinstance(c, dict) and "id" in c}

    # ============================================================
    # scenes 校验
    # ============================================================

    def _validate_scenes(self, scenes: list, valid_ids: set[str]) -> list[ValidationError]:
        errors = []
        if not isinstance(scenes, list):
            return [ValidationError("scenes", "必须是一个数组")]
        if len(scenes) == 0:
            errors.append(ValidationError("scenes", "场景列表不能为空"))
            return errors

        for i, scene in enumerate(scenes):
            prefix = f"scenes[{i}]"

            if not isinstance(scene, dict):
                errors.append(ValidationError(prefix, "场景必须是一个对象"))
                continue

            # 必填字段
            for field in REQUIRED_SCENE_FIELDS:
                if field not in scene:
                    errors.append(ValidationError(f"{prefix}.{field}", f"缺少必填字段 '{field}'"))

            # scene_number 类型
            if "scene_number" in scene and not isinstance(scene["scene_number"], int):
                errors.append(ValidationError(f"{prefix}.scene_number", "scene_number 必须是整数"))

            # heading
            errors.extend(self._validate_heading(scene.get("heading", {}), prefix))

            # action 列表
            errors.extend(self._validate_action(scene.get("action", []), prefix))

            # elements 顺序规则
            errors.extend(self._validate_elements(scene.get("elements", []), prefix, valid_ids))

        return errors

    def _validate_heading(self, heading: dict, prefix: str) -> list[ValidationError]:
        errors = []
        hp = f"{prefix}.heading"

        if not isinstance(heading, dict):
            return [ValidationError(hp, "heading 必须是一个对象")]

        for field in REQUIRED_HEADING_FIELDS:
            if field not in heading:
                errors.append(ValidationError(f"{hp}.{field}", f"缺少必填字段 '{field}'"))

        # context 枚举
        ctx = heading.get("context", "")
        if ctx and ctx not in VALID_CONTEXTS:
            errors.append(ValidationError(f"{hp}.context", f"'{ctx}' 不是合法的 context（应为 {VALID_CONTEXTS}）"))

        # time 枚举
        tm = heading.get("time", "")
        if tm and tm not in VALID_TIMES:
            errors.append(ValidationError(f"{hp}.time", f"'{tm}' 不是合法的 time（应为 {VALID_TIMES}）"))

        return errors

    def _validate_action(self, action: list, prefix: str) -> list[ValidationError]:
        errors = []
        if not isinstance(action, list):
            return [ValidationError(f"{prefix}.action", "action 必须是一个数组")]

        for i, item in enumerate(action):
            if not isinstance(item, dict):
                errors.append(ValidationError(f"{prefix}.action[{i}]", "action 元素必须是对象"))
            elif "text" not in item:
                errors.append(ValidationError(f"{prefix}.action[{i}]", "缺少必填字段 'text'"))
        return errors

    def _validate_elements(self, elements: list, prefix: str, valid_ids: set[str]) -> list[ValidationError]:
        """
        校验 elements 数组的结构规则

        核心规则：
        - dialogue 前面必须有 character（中间最多隔一个 parenthetical）
        - parenthetical 必须在 character 和 dialogue 之间
        - character_id 必须引用已存在的角色
        """
        errors = []
        ep = f"{prefix}.elements"

        if not isinstance(elements, list):
            return [ValidationError(ep, "elements 必须是一个数组")]
        if len(elements) == 0:
            errors.append(ValidationError(ep, "elements 不能为空"))
            return errors

        # 上一个 character 元素在数组中的位置（-1 表示无）
        last_character_idx = -1

        for i, elem in enumerate(elements):
            if not isinstance(elem, dict):
                errors.append(ValidationError(f"{ep}[{i}]", "元素必须是对象"))
                continue

            etype = elem.get("type", "")

            # 类型枚举
            if etype not in VALID_ELEMENT_TYPES:
                errors.append(ValidationError(f"{ep}[{i}].type", f"'{etype}' 不是合法的元素类型（应为 {VALID_ELEMENT_TYPES}）"))
                continue

            if etype == "character":
                char_id = elem.get("character_id", "")
                if not char_id:
                    errors.append(ValidationError(f"{ep}[{i}].character_id", "character 元素缺少 character_id"))
                elif valid_ids and char_id not in valid_ids:
                    errors.append(ValidationError(f"{ep}[{i}].character_id", f"character_id '{char_id}' 不在 dramatis_personae 中"))
                last_character_idx = i

            elif etype == "dialogue":
                if "text" not in elem:
                    errors.append(ValidationError(f"{ep}[{i}].text", "dialogue 元素缺少 text 字段"))
                # 检查前面是否有 character
                if last_character_idx == -1:
                    errors.append(ValidationError(f"{ep}[{i}]", "dialogue 之前必须有 character 元素"))
                else:
                    # 检查中间隔着什么：只允许 parenthetical
                    for j in range(last_character_idx + 1, i):
                        mid_type = elements[j].get("type", "") if isinstance(elements[j], dict) else ""
                        if mid_type not in ("parenthetical",):
                            errors.append(ValidationError(f"{ep}[{i}]", f"dialogue 与上一个 character 之间不允许有 '{mid_type}' 元素"))

            elif etype == "parenthetical":
                if "text" not in elem:
                    errors.append(ValidationError(f"{ep}[{i}].text", "parenthetical 元素缺少 text 字段"))
                # parenthetical 必须在 character 之后
                if last_character_idx == -1:
                    errors.append(ValidationError(f"{ep}[{i}]", "parenthetical 之前必须有 character 元素"))
                # 检查 parenthetical 后面是否有 dialogue（除了当前元素，后面还有的话）
                has_dialogue_after = False
                for j in range(i + 1, len(elements)):
                    future_type = elements[j].get("type", "") if isinstance(elements[j], dict) else ""
                    if future_type == "dialogue":
                        has_dialogue_after = True
                        break
                    elif future_type == "character":
                        break  # 遇到新 character，当前 parenthetical 悬挂

            elif etype == "transition":
                if "text" not in elem:
                    errors.append(ValidationError(f"{ep}[{i}].text", "transition 元素缺少 text 字段"))

        return errors
