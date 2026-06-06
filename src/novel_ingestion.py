"""小说文本读取、清洗、分章"""

import os
import re
import io
import uuid
from datetime import datetime, timezone

from fastapi import UploadFile, HTTPException
from bs4 import BeautifulSoup

from .config import MAX_FILE_SIZE, ALLOWED_EXTENSIONS, CHAPTER_PATTERNS


# ============================================================
# 文本清洗
# ============================================================

def clean_text(text: str) -> str:
    """
    清洗原始文本：统一换行符、去行尾空格、合并连续空行

    Args:
        text: 原始小说文本

    Returns:
        清洗后的文本
    """
    # 统一换行符（Windows \r\n → \n，老 Mac \r → \n）
    text = text.replace("\r\n", "\n").replace("\r", "\n")

    # 去行尾空格
    lines = [line.rstrip() for line in text.split("\n")]

    # 合并连续空行为单个空行
    merged = []
    prev_empty = False
    for line in lines:
        if line == "":
            if not prev_empty:
                merged.append(line)
            prev_empty = True
        else:
            merged.append(line)
            prev_empty = False

    return "\n".join(merged).strip()


# ============================================================
# 分章
# ============================================================

def split_chapters(text: str) -> list[tuple[str, str]]:
    """
    按章节标题将文本拆分为 (标题, 内容) 列表

    章节标题识别配置来自 config.CHAPTER_PATTERNS，
    默认支持：第X章、第X节、Chapter N

    返回格式: [("第一章 xxx", "内容..."), ...]

    Raises:
        ValueError: 找到的章节不足 3 个
    """
    combined = "|".join(CHAPTER_PATTERNS)

    # 找到所有章节标题的位置
    raw_matches = list(re.finditer(combined, text))
    if len(raw_matches) < 3:
        raise ValueError(f"至少需要 3 个章节，实际只找到 {len(raw_matches)} 个章节标记")

    # 转换为 (start, end, title) 三元组
    # start = 标题在原文中的起始字符位置
    # end   = 标题在原文中的结束字符位置（标题最后一个字的下一个位置）
    # title = 标题文本，如 "第一章 大闹天宫"
    matches = [(m.start(), m.end(), m.group()) for m in raw_matches]

    # 处理前言：第一章标题之前的内容
    chapters = []
    if matches[0][0] > 0:
        preface_text = text[: matches[0][0]].strip()
        if preface_text:
            chapters.append(("前言", preface_text))

    # 按标题位置切分章节
    for i, (_start, end, title) in enumerate(matches):
        # 内容从标题后面开始
        content_start = end

        # 内容结束于下一个章节标题之前（最后一章到文末）
        if i + 1 < len(matches):
            content_end = matches[i + 1][0]
        else:
            content_end = len(text)

        content = text[content_start:content_end].strip()
        chapters.append((title.strip(), content))

    return chapters


# ============================================================
# EPUB 提取
# ============================================================

def extract_epub(file_bytes: bytes, filename: str) -> tuple[str, list[tuple[str, str]]]:
    """
    从 EPUB 文件中提取章节文本

    EPUB 本身就是按章节组织的，不需要 split_chapters()。
    用 ebooklib 解析 ZIP 结构，BeautifulSoup 提取 HTML 中的纯文本。

    Args:
        file_bytes: EPUB 文件的原始字节
        filename: 原始文件名（用于推断标题）

    Returns:
        (title, chapters) — title 是书名，chapters 是 [(标题, 内容), ...]

    Raises:
        HTTPException: EPUB 解析失败或章节不足
    """
    import ebooklib
    from ebooklib import epub

    try:
        book = epub.read_epub(io.BytesIO(file_bytes))
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"EPUB 文件解析失败: {e}")

    # 取书名（优先用元数据，否则用文件名）
    titles = book.get_metadata("DC", "title")
    book_title = titles[0][0] if titles else os.path.splitext(filename or "未命名")[0]

    # 获取所有 HTML 文档
    documents = list(book.get_items_of_type(ebooklib.ITEM_DOCUMENT))

    chapters = []
    for i, doc in enumerate(documents):
        # 用 BeautifulSoup 提取纯文本
        soup = BeautifulSoup(doc.get_content(), "html.parser")
        text = soup.get_text()

        # 清洗文本
        text = clean_text(text)
        if not text or len(text) < 50:
            continue

        # 取第一行作为候选标题
        first_line = text.split("\n")[0].strip()
        ch_title = first_line if len(first_line) <= 30 else ""

        chapters.append((ch_title, text))

    # 检测并分离尾注/注释（正文末尾的注释应独立成段）
    chapters = _split_annotations(chapters)

    # 过滤非正文内容（版权页、CIP 等纯元数据，保留序言）
    chapters = _filter_body_chapters(chapters)

    # 如果正文只有一个大段落（非标准 EPUB），尝试拆章
    if len(chapters) < 3:
        body_text = "\n\n".join(t + "\n\n" + c for t, c in chapters)
        # 策略1：正则找章节标记
        try:
            split = split_chapters(body_text)
            if len(split) >= 3:
                chapters = split
        except ValueError:
            pass

    # 策略2：如果仍不足 3 章且 body 只有一个大段落，按字数均分（兜底）
    # 仅当 chapters 只有 1-2 个条目时触发，不会丢弃其他有效章节
    if len(chapters) < 3 and len(chapters) == 1:
        _, body_text = chapters[0]
        if len(body_text) > 6000:
            chapters = _split_by_length(body_text, target_chars=4000)

    if len(chapters) < 3:
        raise HTTPException(
            status_code=400,
            detail=f"EPUB 正文中只找到 {len(chapters)} 个章节，至少需要 3 个（已自动过滤前言/目录/版权/附录）"
        )

    return book_title, chapters


def _split_by_length(text: str, target_chars: int = 4000) -> list[tuple[str, str]]:
    """
    按字数均分长文本（兜底策略，用于无章节标记的流水叙事小说）

    在段落边界处切分，避免切断句子。
    """
    paragraphs = text.split("\n\n")
    chapters = []
    current = []
    current_len = 0
    part_num = 0

    for para in paragraphs:
        current.append(para)
        current_len += len(para)
        if current_len >= target_chars:
            part_num += 1
            ch_title = f"第{part_num}部分"
            chapters.append((ch_title, "\n\n".join(current)))
            current = []
            current_len = 0

    # 收尾
    if current:
        part_num += 1
        ch_title = f"第{part_num}部分"
        chapters.append((ch_title, "\n\n".join(current)))

    return chapters


def _split_annotations(chapters: list[tuple[str, str]]) -> list[tuple[str, str]]:
    """
    检测并分离尾注/注释

    如果某章节末尾含大量单独成行的"注：""注释"等标记，
    将其拆分为正文 + 注释两个独立段。
    """
    ANNOTATION_MARKERS = [
        r'注释',       # "注释"（最宽泛匹配，能覆盖"注释　　⑴"等）
        r'【注】',      # "【注】"
        r'\n注\s*[：:]',# 行首"注："
    ]
    combined = "|".join(ANNOTATION_MARKERS)

    result = []
    for title, text in chapters:
        match = re.search(combined, text)
        if match and match.start() > len(text) * 0.3:
            split_pos = match.start()
            body_text = text[:split_pos].strip()
            notes_text = text[split_pos:].strip()

            # 验证：切分后的"注释"部分至少有 2 个编号条目
            numbered_items = len(re.findall(r'[（(]\d+[）)]', notes_text[:1000]))
            is_likely_endnotes = numbered_items >= 2

            if is_likely_endnotes and len(body_text) > 200 and len(notes_text) > 50:
                result.append((title, body_text))
                notes_title = title + " 注释" if title else "注释"
                result.append((notes_title, notes_text))
                continue

        result.append((title, text))

    return result


def _filter_body_chapters(raw: list[tuple[str, str]]) -> list[tuple[str, str]]:
    """
    过滤掉非正文章节（版权、序言、目录、附录、后记等）

    识别规则：
    - 标题含非正文关键字
    - 内容极短（< 100 字）且不含章节标记
    - 纯目录页（多次出现"第X章"模式）
    """
    SKIP_KEYWORDS = [
        "出版", "编目", "CIP", "ISBN", "插图", "人物表",
    ]

    body = []
    for title, text in raw:
        # 标题含跳过关键字
        skip = False
        for kw in SKIP_KEYWORDS:
            if kw in title:
                skip = True
                break
        if skip:
            continue

        # 纯目录页检测
        markers = len(re.findall(r"第[零一二三四五六七八九十百千0-9]+[章节]", text[:500]))
        if markers >= 3:
            continue

        # 极短内容（扉页、空白页）跳过
        if len(text) < 100:
            continue

        body.append((title, text))

    return body


async def upload_novel(file: UploadFile, db) -> dict:
    """
    处理小说文件上传：校验 → 清洗 → 分章 → 入库

    Args:
        file: FastAPI UploadFile 对象
        db:   数据库连接（get_db() 返回的 sqlite3.Connection）

    Returns:
        {"novel_id": ..., "title": ..., "chapter_count": ..., "chapters": [...]}

    Raises:
        HTTPException(400): 文件校验失败
    """
    # 1. 检查文件后缀
    ext = os.path.splitext(file.filename or "")[1].lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(status_code=400, detail=f"不支持的文件格式 {ext}，请上传 .txt 或 .epub 文件")

    # 2. 读取文件内容
    content = await file.read()

    # 3. 检查文件大小
    if len(content) > MAX_FILE_SIZE:
        size_mb = len(content) / (1024 * 1024)
        raise HTTPException(status_code=400, detail=f"文件过大（{size_mb:.1f}MB），上限 1MB")

    # 4. 根据格式分别处理
    if ext == ".epub":
        # EPUB：章节结构内嵌，无需分章
        title, chapters = extract_epub(content, file.filename)
        text = "\n\n".join(f"{t}\n\n{c}" for t, c in chapters)
    else:
        # TXT：解码 → 清洗 → 正则分章
        try:
            text = content.decode("utf-8")
        except UnicodeDecodeError:
            try:
                text = content.decode("gbk")
            except UnicodeDecodeError:
                raise HTTPException(status_code=400, detail="文件编码错误，请使用 UTF-8 或 GBK 编码")

        text = clean_text(text)
        try:
            chapters = split_chapters(text)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
        title = os.path.splitext(file.filename or "未命名")[0]

    # 8. 写入数据库
    novel_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()

    db.execute(
        """INSERT INTO novels (id, title, original_filename, content, chapter_count, created_at, updated_at)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (novel_id, title, file.filename, text, len(chapters), now, now),
    )

    for i, (ch_title, ch_content) in enumerate(chapters):
        ch_id = str(uuid.uuid4())
        db.execute(
            """INSERT INTO chapters (id, novel_id, chapter_index, title, content, char_count)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (ch_id, novel_id, i, ch_title, ch_content, len(ch_content)),
        )

    db.commit()

    # 9. 返回结果
    return {
        "novel_id": novel_id,
        "title": title,
        "chapter_count": len(chapters),
        "chapters": [
            {"index": i, "title": t, "char_count": len(c)}
            for i, (t, c) in enumerate(chapters)
        ],
    }
