"""수집한 법령 JSON → 읽기 쉬운 텍스트(.txt) + zip.

사용:
  uv run python scripts/export_law_txt.py 민법                # → 민법_20260101.zip (민법.txt)
  uv run python scripts/export_law_txt.py 민법 상법 민사소송법   # 여러 개를 한 zip 으로
편·장·절 제목은 빈 줄로 구분해 남기고, 조문은 항·호까지 펼쳐서 한 문단으로 쓴다.
"""

from __future__ import annotations

import argparse
import json
import zipfile
from pathlib import Path

from civil_rag import config
from civil_rag.ingest.chunking import _flatten, clean_text


def law_to_text(path: Path) -> tuple[str, int]:
    law = json.loads(path.read_text(encoding="utf-8"))["법령"]
    info = law.get("기본정보", {})
    units = law.get("조문", {}).get("조문단위", [])
    if isinstance(units, dict):
        units = [units]
    name = clean_text(info.get("법령명_한글"))
    lines = [
        f"{name} (시행 {info.get('시행일자')}, 공포번호 {info.get('공포번호')})",
        f"출처: 법제처 국가법령정보센터 (open.law.go.kr) · {config.LAW_AS_OF} 시행 버전",
        "",
    ]
    n = 0
    for u in units:
        body = clean_text(u.get("조문내용"))
        if u.get("조문여부") == "전문":      # 편·장·절 제목
            if body:
                lines += ["", body, ""]
            continue
        parts = [body] + _flatten(u.get("항", []))
        lines += ["\n".join(p for p in parts if p), ""]
        n += 1
    return "\n".join(lines).strip() + "\n", n


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("names", nargs="+", help="법령명 (law_collector/data/law_<날짜>/ 안의 파일 이름)")
    ap.add_argument("--out", default=None, help="zip 경로 (기본: <첫 법령명>_<날짜>.zip)")
    a = ap.parse_args(argv)
    out = Path(a.out or f"{a.names[0].replace(' ', '_')}_{config.LAW_AS_OF}.zip")
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for name in a.names:
            src = config.LAW_DIR / f"{name.replace(' ', '_')}.json"
            text, n = law_to_text(src)
            z.writestr(f"{name.replace(' ', '_')}.txt", text.encode("utf-8"))
            print(f"{name}: 조문 {n}개, {len(text):,}자")
    print(f"→ {out} ({out.stat().st_size / 1024:.0f} KB)")


if __name__ == "__main__":
    main()
