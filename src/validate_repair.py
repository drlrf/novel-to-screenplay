"""验证-修复循环

当 Schema 校验发现错误时，将错误信息反馈给 LLM，
由 LLM 修复 JSON → 再次校验 → 最多循环 MAX_REPAIR_CYCLES 轮。
"""

import json

from .config import MAX_REPAIR_CYCLES
from .llm_client import OllamaClient, LLMError
from .schema_validator import ScreenplayValidator, ValidationError
from .prompt_registry import REPAIR_PROMPT


class RepairFailedError(Exception):
    """超过最大修复轮次仍无法通过校验"""
    pass


class RepairLoop:
    """编排修复循环"""

    def __init__(self, llm: OllamaClient):
        self.llm = llm
        self.validator = ScreenplayValidator()

    async def repair(self, screenplay_json: dict) -> tuple[dict, list[dict]]:
        """
        执行验证-修复循环，直到通过或超过最大轮次

        Args:
            screenplay_json: 待校验的剧本 JSON dict

        Returns:
            (valid_json, repair_log)
            repair_log 每轮一条: {"cycle": N, "error_count": N, "errors": [...]}

        Raises:
            RepairFailedError: 超过最大修复轮次
        """
        repair_log = []
        current = screenplay_json

        for cycle in range(MAX_REPAIR_CYCLES + 1):
            errors = self.validator.validate(current)

            log_entry = {
                "cycle": cycle,
                "error_count": len(errors),
                "errors": [{"field": e.field, "message": e.message} for e in errors],
            }
            repair_log.append(log_entry)

            # 无错误 → 通过
            if not errors:
                return current, repair_log

            # 已达最大轮次 → 失败
            if cycle >= MAX_REPAIR_CYCLES:
                raise RepairFailedError(
                    f"修复失败：{MAX_REPAIR_CYCLES} 轮后仍有 {len(errors)} 个错误"
                )

            # 试图修复
            print(f"[Repair] 第{cycle+1}轮：{len(errors)} 个错误，尝试修复...")
            current = await self._do_repair(current, errors)

        return current, repair_log

    async def _do_repair(self, invalid_json: dict, errors: list[ValidationError]) -> dict:
        """
        用 LLM 修复一次

        Args:
            invalid_json: 待修复的 JSON
            errors: 校验错误列表

        Returns:
            修复后的 JSON dict
        """
        # 格式化错误列表
        error_lines = []
        for e in errors:
            error_lines.append(f"  - 字段 {e.field}: {e.message}")
        error_text = "\n".join(error_lines)

        # 格式化 JSON（带缩进，方便 LLM 阅读）
        json_text = json.dumps(invalid_json, ensure_ascii=False, indent=2)

        prompt = REPAIR_PROMPT.format(
            error_list_formatted=error_text,
            invalid_json=json_text,
        )

        try:
            repaired = await self.llm.generate_json(prompt, temperature=0.1)
            return repaired
        except LLMError as e:
            print(f"[Repair] LLM 修复调用失败: {e}")
            # 返回原始 JSON，下一轮重新尝试
            return invalid_json
