"""配置常量"""

import os

# 项目根目录
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# --- LLM 后端选择 ---
# "ollama" 或 "deepseek"
LLM_BACKEND = "deepseek"

# --- Ollama 配置 ---
OLLAMA_BASE_URL = "http://localhost:11434"
MODEL_NAME = "qwen2.5:3b"

# --- DeepSeek 配置 ---
DEEPSEEK_BASE_URL = "https://api.deepseek.com/v1"
DEEPSEEK_API_KEY = "sk-526a1ce03ae84275b86bae45e99735ac"
DEEPSEEK_MODEL = "deepseek-v4-flash"  # 非思考模式，deepseek-chat 将于 2026/07/24 弃用

# --- 通用配置 ---
LLM_TIMEOUT = 120  # 请求超时（秒）
LLM_TEMPERATURE_EXTRACT = 0.3  # 提取阶段：中等，保证一致性
LLM_TEMPERATURE_CONVERT = 0.1  # 转换阶段：低，追求精确
LLM_MAX_RETRIES = 3  # LLM 调用失败最大重试次数

# 文件上传
MAX_FILE_SIZE = 1 * 1024 * 1024  # 1MB
ALLOWED_EXTENSIONS = {".txt", ".epub"}

# 文本分块
CHUNK_MAX_TOKENS = 1800  # 每块最大 token 数
CHUNK_OVERLAP_TOKENS = 200  # 块之间重叠 token 数

# 校验与修复
MAX_REPAIR_CYCLES = 2  # JSON 修复最大轮次（251 个错误的巨型 JSON 修不好再试也没用）

# 章节检测
CHAPTER_PATTERNS = [
    r"第[零一二三四五六七八九十百千0-9]+章",  # 第X章
    r"第[零一二三四五六七八九十百千0-9]+节",  # 第X节
    r"CHAPTER\s+\d+",  # CHAPTER 1
    r"Chapter\s+\d+",  # Chapter 1
]

# 数据库
DB_PATH = os.path.join(BASE_DIR, "screenplay.db")
