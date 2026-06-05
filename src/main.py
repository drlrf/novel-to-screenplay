"""AI 小说转剧本工具 — FastAPI 入口"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from .db import init_db

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


# 挂载静态文件目录（前端界面）
import os
static_dir = os.path.join(os.path.dirname(__file__), "..", "static")
if os.path.isdir(static_dir):
    app.mount("/", StaticFiles(directory=static_dir, html=True), name="static")
