"""PostgreSQL 연결과 스키마 반영 (ADR-006, 04-interfaces-api §10).

- 연결: 명령 실행 1회 = `psycopg.Connection` 1개(`with connect(url) as conn:`).
- 트랜잭션 경계는 응용 서비스가 연다(`with conn.transaction():`). 저장소는 커밋하지 않는다.
- 접속 문자열은 설정(`Settings.secrets`)에서 받는다. 이 모듈은 환경변수를 직접 읽지 않는다.
"""

from __future__ import annotations

from importlib import resources

import psycopg

SCHEMA_PACKAGE = "lawqa.corpus.infrastructure"
SCHEMA_FILE = "schema.sql"


def connect(url: str) -> psycopg.Connection:
    """접속 문자열로 연결을 연다. 호출한 쪽이 `with` 블록으로 닫는다."""
    return psycopg.connect(url)


def read_schema_sql() -> str:
    """패키지에 들어 있는 `schema.sql` 내용."""
    return resources.files(SCHEMA_PACKAGE).joinpath(SCHEMA_FILE).read_text(encoding="utf-8")


def init_schema(conn: psycopg.Connection) -> None:
    """확장·표·색인을 만든다. 모든 문장이 `IF NOT EXISTS`라 여러 번 실행해도 안전하다.

    한 트랜잭션으로 실행해 중간에 실패하면 아무것도 반영하지 않는다.
    """
    with conn.transaction():
        conn.execute(read_schema_sql())
