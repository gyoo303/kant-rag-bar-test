"""정확 일치 답변 캐시 (SQLite).

키 = sha256(정규화 질문 + 사용자 범위 + 문서/색인/프롬프트 버전 + 모델 + 검색 설정 fingerprint + 구성)
→ 문서·색인 버전이 바뀌면 키가 달라져 이전 답변이 재사용되지 않습니다.
TTL 이 지나면 미적중 처리, `invalidate()` 로 명시적 초기화.
"""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import time
from pathlib import Path

from kant_rag.config import Settings


def normalize_question(q: str) -> str:
    return re.sub(r"\s+", " ", q.strip().lower()).rstrip("?？.! ")


def cache_key(question: str, settings: Settings, mode: str, user_scope: str = "public") -> str:
    parts = {
        "q": normalize_question(question),
        "scope": user_scope,
        "versions": settings.versions.model_dump(),
        "model": settings.models.model_dump(),
        "config": settings.fingerprint(),
        "mode": mode,
        "rewrite": settings.optimization.rewrite.enabled,
    }
    return hashlib.sha256(json.dumps(parts, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


class AnswerCache:
    def __init__(self, db_path: Path, ttl_seconds: int):
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(db_path), check_same_thread=False)
        self.ttl = ttl_seconds
        self.conn.execute(
            "CREATE TABLE IF NOT EXISTS answers (key TEXT PRIMARY KEY, value TEXT, created REAL)"
        )

    def get(self, key: str) -> dict | None:
        row = self.conn.execute("SELECT value, created FROM answers WHERE key=?", (key,)).fetchone()
        if not row:
            return None
        if time.time() - row[1] > self.ttl:
            self.conn.execute("DELETE FROM answers WHERE key=?", (key,))
            self.conn.commit()
            return None
        return json.loads(row[0])

    def set(self, key: str, value: dict) -> None:
        self.conn.execute(
            "INSERT OR REPLACE INTO answers VALUES (?, ?, ?)",
            (key, json.dumps(value, ensure_ascii=False), time.time()),
        )
        self.conn.commit()

    def invalidate(self) -> int:
        n = self.conn.execute("DELETE FROM answers").rowcount
        self.conn.commit()
        return n
