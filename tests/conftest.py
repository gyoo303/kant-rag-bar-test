"""공용 시험 픽스처 (DB 담당, 06-quality-gates §2).

`db_conn`: 시험 DB(`DATABASE_URL_TEST`, 데이터베이스 이름은 `_test`로 끝나야 함)에 연결한다.
세션마다 `public` 스키마를 지우고 `init_schema`로 다시 만든다(ADR-006). 시험 하나가 끝나면
그 시험의 변경을 모두 되돌린다(rollback).
"""

from __future__ import annotations

from collections.abc import Iterator

import psycopg
import pytest

from lawqa.shared.db import connect, init_schema
from lawqa.shared.settings import load_settings


@pytest.fixture(scope="session")
def db_url() -> str:
    url = load_settings("base").secrets.database_url_test
    if not url:
        pytest.fail(
            "DATABASE_URL_TEST가 비어 있습니다. `docker compose up -d db` 후 .env에 "
            "postgresql://lawqa:<POSTGRES_PASSWORD>@localhost:5432/lawqa_test 형식으로 넣으세요."
        )
    return url


@pytest.fixture(scope="session")
def fresh_schema(db_url: str) -> None:
    """시험 DB의 스키마를 비우고 다시 만든다. `_test` DB가 아니면 거부한다."""
    with connect(db_url) as conn:
        dbname = conn.info.dbname
        if not dbname.endswith("_test"):
            pytest.fail(
                f"시험 DB 이름은 _test로 끝나야 합니다(현재: {dbname}). 개발 DB를 지우지 않습니다."
            )
        conn.autocommit = True
        conn.execute("DROP SCHEMA IF EXISTS public CASCADE")
        conn.execute("CREATE SCHEMA public")
        init_schema(conn)


@pytest.fixture
def db_conn(db_url: str, fresh_schema: None) -> Iterator[psycopg.Connection]:
    """시험 하나용 연결. 끝나면 변경을 되돌린다."""
    conn = connect(db_url)
    try:
        yield conn
    finally:
        conn.rollback()
        conn.close()
