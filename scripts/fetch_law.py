"""국가법령정보센터 Open API 로 법령 본문을 받아 조문 텍스트(data/raw/statutes/<법령명>.txt)로 저장.

사용:  LAW_OC=<발급받은 OC> uv run python scripts/fetch_law.py 민법 민사소송법 상법 --date 20260101
- OC: https://open.law.go.kr 에서 Open API 신청 후 받는 사용자 ID
- --date: 이 날짜에 시행 중인 법령 버전을 고름 (시험일 기준). 없으면 현행.
출력 형식: 편/장/절 제목 행 + `제N조(제목) 내용` 행 + `① …` 항 행 → ingest/statute.py 가 조문 단위로 청킹.
API 응답 구조가 바뀔 수 있으므로 저장 후 law.go.kr 원문과 몇 조문을 대조하세요.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.parse
import urllib.request
from pathlib import Path

BASE = "https://www.law.go.kr/DRF"
OUT = Path(__file__).resolve().parents[1] / "data" / "raw" / "statutes"


def _get(endpoint: str, **params) -> dict:
    url = f"{BASE}/{endpoint}?" + urllib.parse.urlencode({**params, "type": "JSON"})
    with urllib.request.urlopen(url, timeout=60) as r:
        return json.loads(r.read().decode("utf-8"))


def _as_list(x) -> list:
    return x if isinstance(x, list) else ([] if x is None else [x])


def find_mst(oc: str, name: str, date: str | None) -> tuple[str, dict]:
    """법령명이 정확히 일치하는 법령 중 date 이전 시행된 가장 최신 버전의 MST."""
    res = _get("lawSearch.do", OC=oc, target="law", query=name, display=100)
    laws = [x for x in _as_list(res.get("LawSearch", {}).get("law")) if x.get("법령명한글") == name]
    if date:
        laws = [x for x in laws if x.get("시행일자", "0") <= date] or laws
    if not laws:
        raise SystemExit(f"'{name}' 을 찾지 못했습니다")
    best = max(laws, key=lambda x: x.get("시행일자", ""))
    return best["법령일련번호"], best


def _texts(node) -> list[str]:
    """항/호/목 내용을 순서대로 평탄화."""
    out: list[str] = []
    for key, child in (("항", "항내용"), ("호", "호내용"), ("목", "목내용")):
        for item in _as_list(node.get(key) if isinstance(node, dict) else None):
            if isinstance(item, dict):
                if item.get(child):
                    out.append(str(item[child]).strip())
                out.extend(_texts(item))
    return out


def to_text(law: dict) -> str:
    lines: list[str] = []
    for unit in _as_list(law.get("조문", {}).get("조문단위")):
        content = str(unit.get("조문내용", "")).strip()
        if unit.get("조문여부") == "전문":  # 편/장/절 제목
            if content:
                lines.append(content)
            continue
        if content:
            lines.append(content)
        lines.extend(_texts(unit))
    return "\n".join(lines) + "\n"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("names", nargs="+")
    ap.add_argument("--date", help="YYYYMMDD — 이 날짜 기준 시행 버전")
    args = ap.parse_args()
    oc = os.getenv("LAW_OC")
    if not oc:
        sys.exit("LAW_OC 환경변수(국가법령정보센터 Open API OC)가 필요합니다 (.env)")
    OUT.mkdir(parents=True, exist_ok=True)
    for name in args.names:
        mst, meta = find_mst(oc, name, args.date)
        law = _get("lawService.do", OC=oc, target="law", MST=mst).get("법령", {})
        path = OUT / f"{name}.txt"
        path.write_text(to_text(law), encoding="utf-8")
        print(f"{name}: MST={mst} 시행일자={meta.get('시행일자')} 공포일자={meta.get('공포일자')} → {path}")
        print("  → data/documents.csv 의 version/collected_at 에 위 시행일자와 오늘 날짜를 기입하세요")


if __name__ == "__main__":
    main()
