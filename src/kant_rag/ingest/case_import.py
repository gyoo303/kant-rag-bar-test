"""외부에서 받은 판례 파일 가져오기 → data/raw/cases/cases_<연도>.jsonl

- 입력: 폴더 또는 파일(.json / .jsonl). 한 파일에 판례 1건(객체), 여러 건(배열), 한 줄 1건(JSONL) 모두 허용
- 필드명: 판례 API 상세 응답(한글 키, {"PrecService": {...}} 감싸기 포함)과 우리 형식(영문 키) 모두 인식
- 필터: 시험일 이후 선고 제외, 민사·가사만(사건종류명 또는 사건번호 부호), 판결요지 없는 판례 제외
- 저장: 판결요지·판시사항·참조조문·참조판례만 (판례 전문은 저장하지 않음 → GitHub 용량), 연도별 파일
- 중복: prec_id 또는 사건번호가 이미 data/raw/cases/*.jsonl 에 있으면 건너뜀
"""

from __future__ import annotations

import json
import re
from collections import Counter
from collections.abc import Iterator
from pathlib import Path

from kant_rag.ingest.cases import _clean, case_code

KEYS = {
    "prec_id": ("prec_id", "판례일련번호", "판례정보일련번호", "ID", "id"),
    "case_no": ("case_no", "사건번호"),
    "case_name": ("case_name", "사건명"),
    "court": ("court", "법원명"),
    "decided": ("decided", "선고일자"),
    "kind": ("kind", "사건종류명"),
    "holding_issue": ("holding_issue", "판시사항"),
    "summary": ("summary", "판결요지"),
    "ref_articles": ("ref_articles", "참조조문"),
    "ref_cases": ("ref_cases", "참조판례"),
}


def _iter_records(path: Path) -> Iterator[dict]:
    files = sorted(p for p in path.rglob("*") if p.suffix.lower() in (".json", ".jsonl")) if path.is_dir() else [path]
    for f in files:
        text = f.read_text(encoding="utf-8-sig", errors="replace")
        if f.suffix.lower() == ".jsonl":
            for line in text.splitlines():
                try:
                    yield json.loads(line)
                except ValueError:
                    continue
            continue
        try:
            data = json.loads(text)
        except ValueError:
            continue
        yield from (data if isinstance(data, list) else [data])


def normalize(raw: dict) -> dict:
    if "PrecService" in raw and isinstance(raw["PrecService"], dict):
        raw = raw["PrecService"]
    out = {}
    for k, cands in KEYS.items():
        out[k] = next((_clean(raw[c]) for c in cands if raw.get(c) not in (None, "")), "")
    d = re.sub(r"\D", "", out["decided"])
    out["decided"] = d[:8]
    return out


def existing_ids(cases_dir: Path) -> tuple[set[str], set[str]]:
    pids, nos = set(), set()
    for f in cases_dir.glob("*.jsonl"):
        for line in f.open(encoding="utf-8"):
            try:
                c = json.loads(line)
            except ValueError:
                continue
            pids.add(str(c.get("prec_id", "")))
            nos.add(c.get("case_no", ""))
    return pids, nos


def import_cases(inputs: list[Path], cases_dir: Path, date_to: str, kinds: list[str], codes: list[str],
                 source: str) -> dict:
    cases_dir.mkdir(parents=True, exist_ok=True)
    pids, nos = existing_ids(cases_dir)
    stats: Counter = Counter()
    by_year: dict[str, list[str]] = {}
    for inp in inputs:
        for raw in _iter_records(inp):
            stats["read"] += 1
            c = normalize(raw if isinstance(raw, dict) else {})
            if not c["case_no"] and not c["prec_id"]:
                stats["skip_no_id"] += 1
                continue
            if c["decided"] and c["decided"] > date_to:
                stats["skip_after_exam"] += 1
                continue
            civil = (c["kind"] in kinds) if c["kind"] else (case_code(c["case_no"]) in codes)
            if not civil:
                stats["skip_not_civil"] += 1
                continue
            if not c["summary"]:
                stats["skip_no_summary"] += 1
                continue
            if (c["prec_id"] and c["prec_id"] in pids) or c["case_no"] in nos:
                stats["skip_duplicate"] += 1
                continue
            pids.add(c["prec_id"])
            nos.add(c["case_no"])
            rec = {k: c[k] for k in KEYS if k != "kind"}
            rec["court"] = rec["court"] or "대법원"
            rec["topic"] = None
            rec["source"] = source
            by_year.setdefault(c["decided"][:4] or "unknown", []).append(json.dumps(rec, ensure_ascii=False))
            stats["imported"] += 1
    for year, lines in sorted(by_year.items()):
        with (cases_dir / f"cases_{year}.jsonl").open("a", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")
    sizes = {p.name: round(p.stat().st_size / 1e6, 1) for p in sorted(cases_dir.glob("*.jsonl"))}
    stats_d = dict(stats)
    stats_d["years"] = {y: len(v) for y, v in sorted(by_year.items())}
    stats_d["file_mb_over_90"] = {k: v for k, v in sizes.items() if v > 90}
    stats_d["total_mb"] = round(sum(sizes.values()), 1)
    return stats_d
