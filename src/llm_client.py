"""Ollama LLM 客户端封装"""

import json
import asyncio
import httpx

from .config import OLLAMA_BASE_URL, MODEL_NAME, LLM_TIMEOUT, LLM_MAX_RETRIES


from .exceptions import LLMError


class OllamaClient:
    """封装 Ollama API 调用，提供 chat / generate / generate_json 三种模式"""

    def __init__(self, base_url: str = OLLAMA_BASE_URL, model: str = MODEL_NAME):
        self.base_url = base_url
        self.model = model

    # ============================================================
    # 公开方法
    # ============================================================

    async def chat(self, messages: list[dict], temperature: float = 0.3) -> str:
        """
        多轮对话模式（调 /api/chat）

        Args:
            messages: [{"role": "user", "content": "..."}, ...]
            temperature: 创造性参数（0=确定性, 1=随机）

        Returns:
            模型回复文本
        """
        payload = {
            "model": self.model,
            "messages": messages,
            "stream": False,
            "options": {"temperature": temperature},
        }
        data = await self._post("/api/chat", payload)
        return data["message"]["content"]

    async def generate(self, prompt: str, temperature: float = 0.3) -> str:
        """
        单次生成模式（调 /api/generate）

        Args:
            prompt: 提示词文本
            temperature: 创造性参数

        Returns:
            模型生成文本
        """
        payload = {
            "model": self.model,
            "prompt": prompt,
            "stream": False,
            "options": {"temperature": temperature},
        }
        data = await self._post("/api/generate", payload)
        return data["response"]

    async def generate_json(self, prompt: str, temperature: float = 0.1) -> dict:
        """
        单次生成 + JSON 约束（调 /api/generate，format="json"）

        Args:
            prompt: 提示词文本（需包含 JSON 输出格式说明）
            temperature: 创造性参数（默认 0.1，追求精确）

        Returns:
            解析后的 dict

        Raises:
            LLMError: JSON 解析失败
        """
        payload = {
            "model": self.model,
            "prompt": prompt,
            "stream": False,
            "format": "json",
            "options": {"temperature": temperature},
        }
        data = await self._post("/api/generate", payload)
        raw_text = data["response"]

        try:
            return self._extract_json(raw_text)
        except json.JSONDecodeError as e:
            raise LLMError(f"JSON 解析失败: {e}")

    # ============================================================
    # 内部方法
    # ============================================================

    async def _post(self, endpoint: str, payload: dict) -> dict:
        """发送 POST 请求到 Ollama API（带重试）"""

        async def do_request():
            async with httpx.AsyncClient(timeout=LLM_TIMEOUT) as client:
                resp = await client.post(self.base_url + endpoint, json=payload)
                resp.raise_for_status()
                return resp.json()

        return await self._retry(do_request, label=endpoint)

    async def _retry(self, fn, label: str = ""):
        """重试编排器（指数退避：0.5s → 1s → 2s）"""
        last_error = None
        for attempt in range(LLM_MAX_RETRIES):
            try:
                return await fn()
            except (httpx.HTTPError, httpx.TimeoutException) as e:
                last_error = e
                delay = 0.5 * (2 ** attempt)
                print(f"[{label}] 第{attempt+1}次失败: {e}，{delay}s 后重试")
                await asyncio.sleep(delay)

        raise LLMError(f"{label} 重试 {LLM_MAX_RETRIES} 次后仍失败: {last_error}")

    @staticmethod
    def _extract_json(raw_text: str) -> dict:
        """从 LLM 返回文本中提取 JSON，处理 markdown 代码块包裹等情况"""
        text = raw_text.strip()

        # 去掉 markdown 代码块标记（```json 或 ```）
        if "```" in text:
            lines = text.split("\n")
            lines = [l for l in lines if not l.strip().startswith("```")]
            text = "\n".join(lines).strip()

        # 优先尝试 {} 对象
        left = text.find("{")
        right = text.rfind("}")
        if left != -1 and right != -1 and right > left:
            try:
                return json.loads(text[left:right + 1])
            except json.JSONDecodeError:
                pass

        # 再尝试 [] 数组
        left = text.find("[")
        right = text.rfind("]")
        if left != -1 and right != -1 and right > left:
            try:
                return json.loads(text[left:right + 1])
            except json.JSONDecodeError:
                pass

        # 最后原样解析，失败抛异常
        raise json.JSONDecodeError("无法从文本中提取合法 JSON", text, 0)
