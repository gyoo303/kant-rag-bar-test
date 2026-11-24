"""`law_collector` 출력 읽기 (ADR-015). 판례 `prec/*.json`, 민법 `law/민법.txt`."""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path

from lawqa.corpus.domain.ports import PrecFile

PREC_DIR = "prec"
LAW_DIR = "law"


class FileCollectorReader:
    """raw_dir 아래 파일을 읽는다. 판례는 파일 이름(판례일련번호) 숫자 순으로 돌려준다."""

    def iter_prec_files(self, raw_dir: Path) -> Iterator[PrecFile]:
        prec_dir = raw_dir / PREC_DIR
        if not prec_dir.is_dir():
            return
        for path in sorted(prec_dir.glob("*.json"), key=_numeric_key):
            relative = f"{PREC_DIR}/{path.name}"
            try:
                data = json.loads(path.read_text(encoding="utf-8-sig"))
            except (json.JSONDecodeError, UnicodeDecodeError) as exc:
                yield PrecFile(relative, None, f"{type(exc).__name__}: {exc}")
                continue
            if not isinstance(data, dict):
                yield PrecFile(relative, None, "JSON 최상위가 객체가 아님")
                continue
            yield PrecFile(relative, data)

    def read_law_text(self, raw_dir: Path, name: str = "민법") -> tuple[str, str] | None:
        """`law/<name>.txt` 내용(UTF-8, BOM 허용). 없으면 None."""
        path = raw_dir / LAW_DIR / f"{name}.txt"
        if not path.is_file():
            return None
        return f"{LAW_DIR}/{path.name}", path.read_text(encoding="utf-8-sig")

    def list_law_files(self, raw_dir: Path) -> list[str]:
        law_dir = raw_dir / LAW_DIR
        if not law_dir.is_dir():
            return []
        return sorted(p.name for p in law_dir.iterdir() if p.is_file())


def _numeric_key(path: Path) -> tuple[int, str]:
    stem = path.stem
    return (int(stem), stem) if stem.isdigit() else (2**63, stem)
