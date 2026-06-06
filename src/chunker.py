"""文本分块器 — 将长章节按段落边界切分为 LLM 友好的小块"""

from typing import NamedTuple

from .config import CHUNK_MAX_TOKENS, CHUNK_OVERLAP_TOKENS


class TextChunk(NamedTuple):
    """一个文本块"""
    chunk_index: int        # 块序号（从 0 开始）
    chapter_index: int      # 所属章节序号
    text: str               # 块文本内容
    estimated_tokens: int   # 预估 token 数


class Chunker:
    """
    按段落边界将文本切分为适合 LLM 上下文窗口的小块

    切分策略：
    - 以段落（空行分隔）为最小单位，不在段落内部切断
    - 每块尽量接近 max_tokens，但不超过
    - 相邻块之间保留 overlap_tokens 长度的重叠文本
    """

    def __init__(
        self,
        max_tokens: int = CHUNK_MAX_TOKENS,
        overlap_tokens: int = CHUNK_OVERLAP_TOKENS,
    ):
        self.max_tokens = max_tokens
        self.overlap_tokens = overlap_tokens

    # ============================================================
    # 公开方法
    # ============================================================

    def chunk_chapter(self, chapter_index: int, chapter_text: str) -> list[TextChunk]:
        """
        将一章文本切分为多个块

        Args:
            chapter_index: 章节序号
            chapter_text:  章节全文

        Returns:
            TextChunk 列表，按原文顺序排列
        """
        paragraphs = self._split_paragraphs(chapter_text)
        if not paragraphs:
            return []

        chunks: list[TextChunk] = []
        current_paras: list[str] = []
        current_tokens = 0
        overlap_text = ""  # 上一个块的末尾文本，作为下一个块的开头

        for para in paragraphs:
            para_tokens = self.estimate_tokens(para)

            # 单个段落超过最大 token 数：单独成块（罕见，但需要处理）
            if para_tokens > self.max_tokens:
                # 先保存当前块（如果有内容）
                if current_paras:
                    chunks.append(self._make_chunk(chapter_index, len(chunks), current_paras))
                    current_paras = []
                    current_tokens = 0
                    overlap_text = ""
                # 超大段落强制切分（按字符，保底策略）
                sub_chunks = self._split_long_paragraph(para)
                for sc in sub_chunks:
                    chunks.append(TextChunk(
                        chunk_index=len(chunks),
                        chapter_index=chapter_index,
                        text=sc,
                        estimated_tokens=self.estimate_tokens(sc),
                    ))
                continue

            # 当前段落能加入块中
            if current_tokens + para_tokens <= self.max_tokens:
                current_paras.append(para)
                current_tokens += para_tokens
            else:
                # 当前块已满，封口
                if current_paras:
                    # 提取 overlap 文本（当前块末尾的若干字）
                    full_text = "\n\n".join(current_paras)
                    overlap_text = self._extract_overlap(full_text)
                    chunks.append(TextChunk(
                        chunk_index=len(chunks),
                        chapter_index=chapter_index,
                        text=full_text,
                        estimated_tokens=current_tokens,
                    ))

                # 开新块，带上 overlap
                current_paras = []
                current_tokens = 0
                if overlap_text:
                    current_paras.append(overlap_text)
                    current_tokens = self.estimate_tokens(overlap_text)

                current_paras.append(para)
                current_tokens += para_tokens

        # 最后一个块封口
        if current_paras:
            chunks.append(self._make_chunk(chapter_index, len(chunks), current_paras))

        return chunks

    # ============================================================
    # 内部方法
    # ============================================================

    def _make_chunk(self, chapter_index: int, chunk_index: int, paragraphs: list[str]) -> TextChunk:
        """用段落列表构造一个 TextChunk"""
        text = "\n\n".join(paragraphs)
        return TextChunk(
            chunk_index=chunk_index,
            chapter_index=chapter_index,
            text=text,
            estimated_tokens=self.estimate_tokens(text),
        )

    def _extract_overlap(self, text: str) -> str:
        """从块文本末尾提取 overlap 长度的内容（按字符数估算）"""
        overlap_chars = self.overlap_tokens * 2  # 中文 ~2 chars/token，宽松估算
        if len(text) <= overlap_chars:
            return text
        return text[-overlap_chars:]

    def _split_long_paragraph(self, text: str) -> list[str]:
        """将超过 max_tokens 的单个段落强制按字符切分（保底策略）"""
        max_chars = (self.max_tokens - self.overlap_tokens) * 2
        chunks = []
        for i in range(0, len(text), max_chars):
            chunk_text = text[i:i + max_chars + self.overlap_tokens * 2]
            chunks.append(chunk_text)
        return chunks

    @staticmethod
    def _split_paragraphs(text: str) -> list[str]:
        """按空行将文本拆分为段落列表"""
        raw = text.split("\n\n")
        return [p.strip() for p in raw if p.strip()]

    @staticmethod
    def estimate_tokens(text: str) -> int:
        """
        粗略估算 token 数

        中文约 1.2~1.5 字符/token，英文约 3~4 字符/token。
        保守起见按 1 字符 ≈ 1 token 估算（给 LLM 留足余量）。
        """
        return len(text)
