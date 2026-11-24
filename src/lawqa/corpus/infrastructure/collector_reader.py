"""`law_collector` 출력 읽기 (ADR-015, CR-010). 판례 `prec/*.json`, 법령 `statutes/*.txt`."""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path

from lawqa.corpus.domain.ports import PrecFile, StatuteFile

PREC_DIR = "prec"
STATUTE_DIR = "statutes"
STATUTE_SUFFIX = ".txt"


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

    def iter_statute_texts(self, raw_dir: Path) -> Iterator[StatuteFile]:
        """`statutes/*.txt` 전부를 법령 이름 순으로 읽는다(UTF-8, BOM 허용).

        법령 이름은 파일 이름에서 확장자를 뺀 것이다(CR-010).
        """
        statute_dir = raw_dir / STATUTE_DIR
        if not statute_dir.is_dir():
            return
        for path in sorted(statute_dir.glob(f"*{STATUTE_SUFFIX}")):
            yield StatuteFile(
                law_name=path.stem,
                path=f"{STATUTE_DIR}/{path.name}",
                text=path.read_text(encoding="utf-8-sig"),
            )

    def list_ignored_statute_files(self, raw_dir: Path) -> list[str]:
        """`statutes/` 안에서 읽지 않은 파일 이름(`.txt`가 아닌 것). 보고용."""
        statute_dir = raw_dir / STATUTE_DIR
        if not statute_dir.is_dir():
            return []
        return sorted(
            p.name for p in statute_dir.iterdir() if p.is_file() and p.suffix != STATUTE_SUFFIX
        )


def _numeric_key(path: Path) -> tuple[int, str]:
    stem = path.stem
    return (int(stem), stem) if stem.isdigit() else (2**63, stem)
