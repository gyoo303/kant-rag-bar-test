"""버전 해시 (04-interfaces-api §1.1). 표준 라이브러리만 사용 — 도메인에서도 import 가능."""

from __future__ import annotations

import hashlib
from pathlib import Path


def sha256_of(data: bytes) -> str:
    """바이트열의 SHA-256 16진 문자열."""
    return hashlib.sha256(data).hexdigest()


def sha256_of_files(paths: list[Path]) -> str:
    """여러 파일을 이름 순으로 정렬해 (파일 이름, 내용)을 이어 붙인 SHA-256.

    파일 이름을 함께 넣어 내용이 같고 이름만 바뀐 경우도 다른 해시가 되게 한다.
    """
    digest = hashlib.sha256()
    for path in sorted(paths, key=lambda p: p.name):
        digest.update(path.name.encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()
