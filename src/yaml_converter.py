"""JSON → YAML 确定性转换

不做任何 LLM 调用，纯 Python 代码。
用 ruamel.yaml 保留 key 顺序，处理中文无问题。
"""

from ruamel.yaml import YAML
from ruamel.yaml.scalarstring import LiteralScalarString


def dict_to_yaml(data: dict) -> str:
    """
    将剧本 JSON dict 转换为格式化的 YAML 字符串

    处理：
    - 保留 key 的输出顺序（与 dict 定义顺序一致）
    - 长文本字段使用 | 块标量（更可读）
    - 中文无转义

    Args:
        data: 剧本 JSON dict（已通过 Schema 校验）

    Returns:
        YAML 字符串
    """
    yaml = YAML()
    yaml.indent(mapping=2, sequence=4, offset=2)
    yaml.allow_unicode = True
    yaml.default_flow_style = False
    yaml.width = 120  # 避免过早换行

    # 对长文本字段应用块标量格式
    data = _apply_literal_blocks(data)

    import io
    buf = io.StringIO()
    yaml.dump(data, buf)
    return buf.getvalue()


def dict_to_yaml_file(data: dict, filepath: str) -> None:
    """将剧本 JSON dict 写入 YAML 文件"""
    yaml_str = dict_to_yaml(data)
    with open(filepath, "w", encoding="utf-8") as f:
        f.write(yaml_str)


def _apply_literal_blocks(data: dict) -> dict:
    """
    递归遍历 dict，将长度超过阈值的字符串标记为 YAML 块标量

    块标量（| 前缀）比引号包裹更可读，适合多行文本。
    """
    processed = {}
    for key, value in data.items():
        if isinstance(value, str) and len(value) > 60:
            processed[key] = LiteralScalarString(value)
        elif isinstance(value, dict):
            processed[key] = _apply_literal_blocks(value)
        elif isinstance(value, list):
            processed[key] = [
                _apply_literal_blocks(item) if isinstance(item, dict) else item
                for item in value
            ]
        else:
            processed[key] = value
    return processed
