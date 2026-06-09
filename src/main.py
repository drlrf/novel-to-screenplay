"""AI 小说转剧本工具 — FastAPI 入口"""

import os
import json
import uuid
import asyncio
from datetime import datetime, timezone

from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import JSONResponse

from .config import MODEL_NAME, LLM_BACKEND
from .db import init_db, get_db
from .novel_ingestion import upload_novel
from .chunker import Chunker
from .stage1_extraction import Stage1Extractor, NarrativeData
from .stage2_conversion import Stage2Converter
from .validate_repair import RepairLoop

# 根据配置选择 LLM 后端
if LLM_BACKEND == "deepseek":
    from .deepseek_client import DeepSeekClient as LLMClient
    print("[main] 使用 DeepSeek API")
else:
    from .llm_client import OllamaClient as LLMClient
    from .llm_client import LLMError
    print(f"[main] 使用 Ollama ({MODEL_NAME})")

app = FastAPI(title="AI 小说转剧本工具")

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def startup():
    """服务启动时初始化数据库"""
    init_db()


@app.get("/health")
def health():
    """健康检查"""
    return {"status": "ok"}


# ============================================================
# 小说上传与管理 API
# ============================================================

@app.post("/api/novel/upload")
async def api_upload_novel(file: UploadFile = File(...)):
    """上传小说 .txt 文件，自动分章并入库"""
    with get_db() as db:
        return await upload_novel(file, db)


@app.get("/api/novels")
def api_list_novels():
    """列出所有已上传的小说"""
    with get_db() as db:
        rows = db.execute(
            "SELECT id, title, chapter_count, created_at FROM novels ORDER BY created_at DESC"
        ).fetchall()
        return [dict(r) for r in rows]


@app.get("/api/novel/{novel_id}")
def api_get_novel(novel_id: str):
    """获取指定小说的章节信息"""
    with get_db() as db:
        novel = db.execute("SELECT * FROM novels WHERE id = ?", (novel_id,)).fetchone()
        if not novel:
            raise HTTPException(status_code=404, detail="小说不存在")

        chapters = db.execute(
            "SELECT id, chapter_index, title, char_count FROM chapters WHERE novel_id = ? ORDER BY chapter_index",
            (novel_id,),
        ).fetchall()

        return {
            "novel": dict(novel),
            "chapters": [dict(c) for c in chapters],
        }


@app.delete("/api/novel/{novel_id}")
def api_delete_novel(novel_id: str):
    """删除小说及其关联数据（级联删除章节和剧本）"""
    with get_db() as db:
        novel = db.execute("SELECT id FROM novels WHERE id = ?", (novel_id,)).fetchone()
        if not novel:
            raise HTTPException(status_code=404, detail="小说不存在")
        db.execute("DELETE FROM novels WHERE id = ?", (novel_id,))
        return {"ok": True}


# ============================================================
# Stage 1 提取 API
# ============================================================

# 全局实例（服务生命周期内复用）
llm_client = LLMClient()
chunker = Chunker()
extractor = Stage1Extractor(llm_client)

# 任务状态内存存储（单用户场景，不需要持久化队列）
_jobs: dict[str, dict] = {}


def _job_progress(job_id: str) -> dict:
    """查询任务进度"""
    job = _jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="任务不存在")
    return {
        "job_id": job_id,
        "status": job["status"],
        "progress": job["progress"],
        "result": job.get("result"),
    }


async def _run_extraction(job_id: str, novel_id: str, chapter_indexes: list[int]):
    """后台执行 Stage 1 提取"""
    job = _jobs[job_id]
    try:
        # 进度：读取章节
        job["progress"] = {"stage": "reading", "percent": 5, "detail": "读取章节..."}
        with get_db() as db:
            rows = db.execute(
                "SELECT chapter_index, content FROM chapters WHERE novel_id = ? AND chapter_index IN ({}) ORDER BY chapter_index".format(
                    ",".join("?" * len(chapter_indexes))
                ),
                (novel_id, *chapter_indexes),
            ).fetchall()

        if not rows:
            raise ValueError("未找到选中章节")

        # 进度：分块
        job["progress"] = {"stage": "chunking", "percent": 10, "detail": "文本分块..."}
        all_chunks = []
        for row in rows:
            chunks = chunker.chunk_chapter(row["chapter_index"], row["content"])
            all_chunks.extend(chunks)

        job["progress"] = {"stage": "chunking", "percent": 20, "detail": f"已切分为 {len(all_chunks)} 个块"}

        # 进度：角色提取
        job["progress"] = {"stage": "extracting", "percent": 25, "detail": "提取角色..."}
        narrative = await extractor.run(all_chunks)

        # 序列化结果
        result_json = json.dumps(narrative.to_dict(), ensure_ascii=False)
        job["progress"] = {"stage": "saving", "percent": 95, "detail": "保存结果..."}

        # 存入数据库
        now = datetime.now(timezone.utc).isoformat()
        screenplay_id = str(uuid.uuid4())
        with get_db() as db:
            db.execute(
                """INSERT INTO screenplays (id, novel_id, chapter_indexes, stage1_result, status, character_count, scene_count, created_at)
                   VALUES (?, ?, ?, ?, 'stage1_done', ?, ?, ?)""",
                (screenplay_id, novel_id, json.dumps(chapter_indexes), result_json,
                 len(narrative.characters), len(narrative.scenes), now),
            )
            db.commit()

        job["status"] = "complete"
        job["progress"] = {"stage": "done", "percent": 100, "detail": "Stage 1 完成"}
        job["result"] = {
            "screenplay_id": screenplay_id,
            "character_count": len(narrative.characters),
            "scene_count": len(narrative.scenes),
            "dialogue_count": len(narrative.dialogues),
        }

    except Exception as e:
        job["status"] = "failed"
        job["progress"] = {"stage": "error", "percent": 0, "detail": str(e)}


@app.post("/api/extract/start")
async def api_start_extraction(payload: dict):
    """
    触发 Stage 1 提取

    Request: {"novel_id": "...", "chapter_indexes": [0, 1, 2]}
    Response: {"job_id": "...", "status": "running"}
    """
    novel_id = payload.get("novel_id")
    chapter_indexes = payload.get("chapter_indexes", [])

    if not novel_id:
        raise HTTPException(status_code=400, detail="缺少 novel_id")
    if len(chapter_indexes) < 3:
        raise HTTPException(status_code=400, detail="至少选择 3 个章节")

    # 验证小说和章节存在
    with get_db() as db:
        novel = db.execute("SELECT id FROM novels WHERE id = ?", (novel_id,)).fetchone()
        if not novel:
            raise HTTPException(status_code=404, detail="小说不存在")

    job_id = str(uuid.uuid4())[:8]
    _jobs[job_id] = {"status": "running", "progress": {}, "result": None}

    # 启动后台任务
    asyncio.create_task(_run_extraction(job_id, novel_id, chapter_indexes))

    return {"job_id": job_id, "status": "running"}


@app.get("/api/extract/{job_id}/status")
def api_extract_status(job_id: str):
    """查询提取任务进度"""
    return _job_progress(job_id)


# ============================================================
# Stage 2 转换 & YAML 输出 API
# ============================================================

converter = Stage2Converter(llm_client)


async def _run_conversion(job_id: str, screenplay_id: str):
    """后台执行 Stage 2 转换"""
    job = _jobs[job_id]
    try:
        job["progress"] = {"stage": "loading", "percent": 5, "detail": "加载 Stage 1 结果..."}

        # 从数据库加载 Stage 1 结果
        with get_db() as db:
            row = db.execute(
                "SELECT stage1_result, novel_id FROM screenplays WHERE id = ?",
                (screenplay_id,),
            ).fetchone()
            if not row or not row["stage1_result"]:
                raise ValueError("未找到 Stage 1 结果")

            novel_row = db.execute(
                "SELECT title FROM novels WHERE id = ?", (row["novel_id"],)
            ).fetchone()

        narrative = NarrativeData.from_dict(json.loads(row["stage1_result"]))
        meta = {"title": novel_row["title"] if novel_row else "未命名", "author": "佚名"}

        job["progress"] = {"stage": "converting", "percent": 30, "detail": "LLM 组装剧本 JSON..."}

        # 执行 Stage 2 转换
        result = await converter.convert(narrative, meta)

        job["progress"] = {"stage": "saving", "percent": 90, "detail": "保存结果..."}

        # 更新数据库
        now = datetime.now(timezone.utc).isoformat()
        with get_db() as db:
            db.execute(
                """UPDATE screenplays
                   SET stage2_json = ?, yaml_output = ?, status = 'complete', completed_at = ?,
                       character_count = ?, scene_count = ?
                   WHERE id = ?""",
                (
                    json.dumps(result["json"], ensure_ascii=False),
                    result["yaml"],
                    now,
                    len(narrative.characters),
                    len(narrative.scenes),
                    screenplay_id,
                ),
            )
            db.commit()

        job["status"] = "complete"
        job["progress"] = {"stage": "done", "percent": 100, "detail": "剧本生成完成"}
        job["result"] = {
            "screenplay_id": screenplay_id,
            "repair_cycles": len(result["repair_log"]),
        }

    except Exception as e:
        job["status"] = "failed"
        job["progress"] = {"stage": "error", "percent": 0, "detail": str(e)}


@app.post("/api/convert/start")
async def api_start_conversion(payload: dict):
    """
    触发 Stage 2 转换

    Request: {"screenplay_id": "..."}
    Response: {"job_id": "...", "status": "running"}
    """
    screenplay_id = payload.get("screenplay_id")
    if not screenplay_id:
        raise HTTPException(status_code=400, detail="缺少 screenplay_id")

    # 验证 screenplay 存在
    with get_db() as db:
        row = db.execute(
            "SELECT id, status FROM screenplays WHERE id = ?", (screenplay_id,)
        ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="screenplay 不存在")
        if row["status"] != "stage1_done":
            raise HTTPException(status_code=400, detail="Stage 1 尚未完成")

    job_id = str(uuid.uuid4())[:8]
    _jobs[job_id] = {"status": "running", "progress": {}, "result": None}
    asyncio.create_task(_run_conversion(job_id, screenplay_id))

    return {"job_id": job_id, "status": "running"}


@app.get("/api/convert/{job_id}/status")
def api_convert_status(job_id: str):
    """查询转换任务进度"""
    return _job_progress(job_id)


@app.get("/api/screenplay/{screenplay_id}")
def api_get_screenplay(screenplay_id: str, format: str = "yaml"):
    """
    获取最终剧本

    Query params:
        format: "yaml" (默认) 或 "json"
    """
    with get_db() as db:
        row = db.execute(
            "SELECT * FROM screenplays WHERE id = ?", (screenplay_id,)
        ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="剧本不存在")
        if row["status"] != "complete":
            raise HTTPException(status_code=400, detail=f"剧本尚未完成，当前状态: {row['status']}")

    if format == "json":
        return JSONResponse(content=json.loads(row["stage2_json"]))
    else:
        return JSONResponse(content={"yaml": row["yaml_output"]})


@app.get("/api/screenplay/{screenplay_id}/download")
def api_download_screenplay(screenplay_id: str):
    """下载 YAML 文件"""
    with get_db() as db:
        row = db.execute(
            "SELECT yaml_output, title FROM screenplays s JOIN novels n ON s.novel_id = n.id WHERE s.id = ?",
            (screenplay_id,),
        ).fetchone()
        if not row or not row["yaml_output"]:
            raise HTTPException(status_code=404, detail="剧本不存在或未完成")

    from fastapi.responses import PlainTextResponse
    safe_title = row["title"].replace(" ", "_")[:30]
    return PlainTextResponse(
        content=row["yaml_output"],
        media_type="application/x-yaml",
        headers={"Content-Disposition": f"attachment; filename={safe_title}_screenplay.yaml"},
    )


# 挂载静态文件目录（前端界面）
static_dir = os.path.join(os.path.dirname(__file__), "..", "static")
if os.path.isdir(static_dir):
    app.mount("/", StaticFiles(directory=static_dir, html=True), name="static")
