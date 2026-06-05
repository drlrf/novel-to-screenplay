"""小说文本读取、清洗、分章"""

import os
import re
import uuid
from datetime import datetime, timezone

from fastapi import UploadFile, HTTPException

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
# 上传入口（被 main.py 的路由调用）
# ============================================================

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
        raise HTTPException(status_code=400, detail=f"不支持的文件格式 {ext}，请上传 .txt 文件")

    # 2. 读取文件内容
    content = await file.read()

    # 3. 检查文件大小
    if len(content) > MAX_FILE_SIZE:
        size_mb = len(content) / (1024 * 1024)
        raise HTTPException(status_code=400, detail=f"文件过大（{size_mb:.1f}MB），上限 1MB")

    # 4. 解码为文本（尝试 UTF-8，失败尝试 GBK）
    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError:
        try:
            text = content.decode("gbk")
        except UnicodeDecodeError:
            raise HTTPException(status_code=400, detail="文件编码错误，请使用 UTF-8 或 GBK 编码")

    # 5. 清洗文本
    text = clean_text(text)

    # 6. 分章
    try:
        chapters = split_chapters(text)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    # 7. 从文件名推断标题
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
