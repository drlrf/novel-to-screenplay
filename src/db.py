"""数据库初始化与连接管理"""

import sqlite3

from .config import DB_PATH


def get_db() -> sqlite3.Connection:
    """获取数据库连接（row_factory 设置为 Row，支持字典式访问）"""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db() -> None:
    """初始化数据库表结构"""
    with get_db() as conn:
        conn.executescript("""
            -- 小说源文件
            CREATE TABLE IF NOT EXISTS novels (
                id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                original_filename TEXT,
                content TEXT NOT NULL,
                chapter_count INTEGER DEFAULT 0,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            -- 章节
            CREATE TABLE IF NOT EXISTS chapters (
                id TEXT PRIMARY KEY,
                novel_id TEXT NOT NULL,
                chapter_index INTEGER NOT NULL,
                title TEXT,
                content TEXT NOT NULL,
                char_count INTEGER DEFAULT 0,
                FOREIGN KEY (novel_id) REFERENCES novels(id) ON DELETE CASCADE
            );

            -- 剧本生成结果
            CREATE TABLE IF NOT EXISTS screenplays (
                id TEXT PRIMARY KEY,
                novel_id TEXT NOT NULL,
                chapter_indexes TEXT NOT NULL,
                stage1_result TEXT,
                stage2_json TEXT,
                yaml_output TEXT,
                character_count INTEGER DEFAULT 0,
                scene_count INTEGER DEFAULT 0,
                status TEXT DEFAULT 'pending',
                error_log TEXT,
                created_at TEXT NOT NULL,
                completed_at TEXT,
                FOREIGN KEY (novel_id) REFERENCES novels(id) ON DELETE CASCADE
            );
        """)
