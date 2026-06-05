"""配置常量"""

import os

# 项目根目录
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# Ollama 配置
OLLAMA_BASE_URL = "http://localhost:11434"
MODEL_NAME = "qwen2.5:1.5b"
LLM_TIMEOUT = 120  # 请求超时（秒）
LLM_TEMPERATURE_EXTRACT = 0.3  # 提取阶段：中等，保证一致性
LLM_TEMPERATURE_CONVERT = 0.1  # 转换阶段：低，追求精确
LLM_MAX_RETRIES = 3  # LLM 调用失败最大重试次数

# 文件上传
MAX_FILE_SIZE = 1 * 1024 * 1024  # 1MB
ALLOWED_EXTENSIONS = {".txt"}

# 文本分块
CHUNK_MAX_TOKENS = 1800  # 每块最大 token 数
CHUNK_OVERLAP_TOKENS = 200  # 块之间重叠 token 数

# 校验与修复
MAX_REPAIR_CYCLES = 3  # JSON 修复最大轮次

# 章节检测
CHAPTER_PATTERNS = [
    r"第[零一二三四五六七八九十百千0-9]+章",  # 第X章
    r"第[零一二三四五六七八九十百千0-9]+节",  # 第X节
    r"CHAPTER\s+\d+",  # CHAPTER 1
    r"Chapter\s+\d+",  # Chapter 1
]

# 数据库
DB_PATH = os.path.join(BASE_DIR, "screenplay.db")
