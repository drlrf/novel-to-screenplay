"""DeepSeek API 客户端 — OpenAI 兼容接口"""

import json
import asyncio
import httpx

from .config import DEEPSEEK_BASE_URL, DEEPSEEK_API_KEY, DEEPSEEK_MODEL, LLM_TIMEOUT, LLM_MAX_RETRIES


from .exceptions import LLMError


class DeepSeekClient:
    """DeepSeek API 封装，接口与 OllamaClient 一致"""

    def __init__(self, base_url: str = DEEPSEEK_BASE_URL, model: str = DEEPSEEK_MODEL):
        self.base_url = base_url
        self.model = model
        self._headers = {
            "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
            "Content-Type": "application/json",
        }

    # ============================================================
    # 公开方法
    # ============================================================

    async def chat(self, messages: list[dict], temperature: float = 0.3) -> str:
        """多轮对话"""
        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
        }
        data = await self._post("/chat/completions", payload)
        return data["choices"][0]["message"]["content"]

    async def generate(self, prompt: str, temperature: float = 0.3) -> str:
        """单次生成（封装为单条 user message）"""
        messages = [{"role": "user", "content": prompt}]
        return await self.chat(messages, temperature)

    async def generate_json(self, prompt: str, temperature: float = 0.1) -> dict:
        """单次生成 + JSON 约束"""
        # DeepSeek 的 JSON mode 需要在 prompt 中明确提到 JSON，
        # 且用 response_format 参数约束
        messages = [{"role": "user", "content": prompt}]
        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "response_format": {"type": "json_object"},
        }
        data = await self._post("/chat/completions", payload)
        raw_text = data["choices"][0]["message"]["content"]

        try:
            return self._extract_json(raw_text)
        except json.JSONDecodeError as e:
            raise LLMError(f"JSON 解析失败: {e}")

    # ============================================================
    # 内部方法
    # ============================================================

    async def _post(self, endpoint: str, payload: dict) -> dict:
        """发送 POST 请求（带重试）"""
        async def do_request():
            async with httpx.AsyncClient(timeout=LLM_TIMEOUT) as client:
                resp = await client.post(
                    self.base_url + endpoint,
                    json=payload,
                    headers=self._headers,
                )
                resp.raise_for_status()
                return resp.json()

        return await self._retry(do_request, label=endpoint)

    async def _retry(self, fn, label: str = ""):
        """重试编排器（指数退避）"""
        last_error = None
        for attempt in range(LLM_MAX_RETRIES):
            try:
                return await fn()
            except (httpx.HTTPError, httpx.TimeoutException) as e:
                last_error = e
                delay = 0.5 * (2 ** attempt)
                print(f"[DeepSeek:{label}] 第{attempt+1}次失败: {e}，{delay}s 后重试")
                await asyncio.sleep(delay)

        raise LLMError(f"{label} 重试 {LLM_MAX_RETRIES} 次后仍失败: {last_error}")

    @staticmethod
    def _extract_json(raw_text: str) -> dict:
        """从返回文本中提取 JSON"""
        text = raw_text.strip()

        # 去掉 markdown 代码块
        if "```" in text:
            lines = text.split("\n")
            lines = [l for l in lines if not l.strip().startswith("```")]
            text = "\n".join(lines).strip()

        # 优先 {} 对象
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

        raise json.JSONDecodeError("无法提取 JSON", text, 0)
