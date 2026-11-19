"""사용자별 학습 기록 저장소 (SQLite).

콘텐츠(분석 결과, 개념, 원칙)는 파일로 두고, 사용자마다 달라지는 것만 여기에 둔다:
프로필, 문제 풀이 기록, 간격 반복 일정, 내 게임, 판 전 목표.
실서비스에서 Postgres로 옮길 때 이 모듈만 바꾸면 되게, SQL은 여기 밖으로 내보내지 않는다.
"""

from __future__ import annotations

import datetime as dt
import json
import os
import sqlite3
import threading
from pathlib import Path

from fastapi import Header

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = Path(os.environ.get("JUNGLE_DB", ROOT / "data" / "app.db"))

SCHEMA = [
    # v1
    """
    CREATE TABLE users (
      id TEXT PRIMARY KEY,
      name TEXT,
      tier TEXT,              -- 아이언 ~ 챌린저
      division TEXT,
      role TEXT DEFAULT '정글',
      weekly_games INTEGER,
      goal_tier TEXT,
      created TEXT NOT NULL
    );
    CREATE TABLE attempts (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      user_id TEXT NOT NULL,
      item_id TEXT NOT NULL,
      category TEXT,
      choice INTEGER,          -- 고른 선택지 번호(원래 순서). 시간 초과면 NULL
      correct INTEGER NOT NULL,
      confidence INTEGER NOT NULL, -- 0 찍음, 1 아마, 2 확실
      ms INTEGER,
      created TEXT NOT NULL
    );
    CREATE INDEX attempts_user ON attempts(user_id, created);
    CREATE TABLE srs (
      user_id TEXT NOT NULL,
      item_id TEXT NOT NULL,
      reps INTEGER NOT NULL DEFAULT 0,
      interval_days REAL NOT NULL DEFAULT 0,
      ease REAL NOT NULL DEFAULT 2.5,
      lapses INTEGER NOT NULL DEFAULT 0,
      due TEXT NOT NULL,
      last_correct INTEGER,
      last_confidence INTEGER,
      updated TEXT NOT NULL,
      PRIMARY KEY (user_id, item_id)
    );
    CREATE TABLE my_games (
      id TEXT PRIMARY KEY,
      user_id TEXT NOT NULL,
      dir TEXT NOT NULL,       -- VODS 기준 폴더 (mine/<user>/<id>)
      title TEXT,
      champion TEXT,
      result TEXT,
      played TEXT,             -- 게임한 날짜
      created TEXT NOT NULL
    );
    CREATE INDEX my_games_user ON my_games(user_id, created);
    CREATE TABLE goals (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      user_id TEXT NOT NULL,
      rule_id TEXT,
      text TEXT NOT NULL,      -- "이러면 → 이렇게"
      game_id TEXT,            -- 이 목표로 한 내 게임 (분석 뒤 연결)
      followed TEXT,           -- yes | partial | no | na(그 상황이 안 나옴)
      note TEXT,
      created TEXT NOT NULL
    );
    """,
    # v2: 녹화 에이전트, 내 게임 상태
    """
    ALTER TABLE users ADD COLUMN auto_analyze INTEGER NOT NULL DEFAULT 1;
    CREATE TABLE agent_tokens (
      hash TEXT PRIMARY KEY,   -- 토큰의 sha256. 원문은 저장하지 않는다
      user_id TEXT NOT NULL,
      label TEXT,
      created TEXT NOT NULL,
      last_seen TEXT
    );
    ALTER TABLE my_games ADD COLUMN goal_id INTEGER;
    ALTER TABLE my_games ADD COLUMN metrics TEXT;   -- JSON: 게임 기록으로 계산한 지표
    ALTER TABLE my_games ADD COLUMN role TEXT;
    """,
]

_lock = threading.Lock()
_conn: sqlite3.Connection | None = None


def conn() -> sqlite3.Connection:
    global _conn
    if _conn is None:
        DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        c = sqlite3.connect(DB_PATH, check_same_thread=False)
        c.row_factory = sqlite3.Row
        c.execute("PRAGMA journal_mode=WAL")
        version = c.execute("PRAGMA user_version").fetchone()[0]
        for i, sql in enumerate(SCHEMA[version:], start=version + 1):
            c.executescript(sql)
            c.execute(f"PRAGMA user_version = {i}")
        c.commit()
        _conn = c
    return _conn


def q(sql: str, args: tuple = ()) -> list[dict]:
    with _lock:
        return [dict(r) for r in conn().execute(sql, args).fetchall()]


def x(sql: str, args: tuple = ()) -> int:
    with _lock:
        c = conn()
        cur = c.execute(sql, args)
        c.commit()
        return cur.lastrowid or 0


def now() -> str:
    return dt.datetime.now().isoformat(timespec="seconds")


def today() -> str:
    return dt.date.today().isoformat()


# ---------- 사용자 ----------
# 지금은 로그인 없이 기기 하나 = 사용자 하나("local"). 실서비스에선 인증 미들웨어가 X-User-Id를 채운다.
def current_user(x_user_id: str | None = Header(default=None)) -> str:
    uid = (x_user_id or "local").strip()[:64] or "local"
    if not q("SELECT 1 FROM users WHERE id = ?", (uid,)):
        x("INSERT INTO users (id, created) VALUES (?, ?)", (uid, now()))
    return uid


def get_profile(uid: str) -> dict:
    rows = q("SELECT * FROM users WHERE id = ?", (uid,))
    return rows[0] if rows else {"id": uid}


PROFILE_FIELDS = ("name", "tier", "division", "role", "weekly_games", "goal_tier", "auto_analyze")


def set_profile(uid: str, data: dict) -> dict:
    fields = {k: data[k] for k in PROFILE_FIELDS if k in data}
    if fields:
        sets = ", ".join(f"{k} = ?" for k in fields)
        x(f"UPDATE users SET {sets} WHERE id = ?", (*fields.values(), uid))
    return get_profile(uid)


def dumps(o) -> str:
    return json.dumps(o, ensure_ascii=False)
