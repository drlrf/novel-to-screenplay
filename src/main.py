"""AI 小说转剧本工具 — FastAPI 入口"""

import os

from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import JSONResponse

from .db import init_db, get_db
from .novel_ingestion import upload_novel

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


# 挂载静态文件目录（前端界面）
static_dir = os.path.join(os.path.dirname(__file__), "..", "static")
if os.path.isdir(static_dir):
    app.mount("/", StaticFiles(directory=static_dir, html=True), name="static")
