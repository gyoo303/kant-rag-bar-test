"""판례 변경 관계 (전원합의체가 이전 판례를 변경한 것) → 색인 폴더의 overruled.json

2026 문 13: 모델이 91다6658(법정지상권)을 근거로 확신했지만, 같은 쟁점을 다룬 2002다9660 전원합의체 이후
그대로 쓰면 안 되는 판례였다. 판시사항·판결요지에는 변경 사실이 거의 안 나오고(전체 청크 중 44건),
판결 이유(판례내용)의 "…판결은 이 판결의 견해에 배치되는 범위에서 이를 변경하기로 한다" 문장에 나온다.
그 문장에서 사건번호를 뽑아 {변경된 사건번호: [변경한 판결]} 을 만든다.

시험 시점 이후 판결로 변경된 사실은 쓰지 않는다 (date_to = 판례 선고일 상한, 색인과 같은 값).
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from civil_rag import config

_CHANGE = re.compile(r"변경하기로\s*한다")
_CASE = re.compile(r"(\d{2,4})\s*([가-힣]{1,4})\s*(\d{1,6})")
_SENT_END = re.compile(r"다\.\s")
_TAG = re.compile(r"<[^>]+>")
WINDOW = 1500


def norm_case(no: str) -> str:
    return re.sub(r"\s+", "", no or "")


def overruled_cases_in(body: str, own: set[str]) -> list[str]:
    """판결 이유에서 '변경하기로 한다' 문장마다 그 문장 안의 사건번호(자기 사건 제외)."""
    body = _TAG.sub(" ", body or "")
    out: list[str] = []
    for m in _CHANGE.finditer(body):
        start = max(0, m.start() - WINDOW)
        window = body[start:m.start()]
        ends = list(_SENT_END.finditer(window))
        sent = window[ends[-1].end():] if ends else window
        for c in _CASE.finditer(sent):
            no = "".join(c.groups())
            if no not in own and no not in out:
                out.append(no)
    return out


def build_overruled(date_to: str | None = None, prec_dir: Path | None = None) -> dict:
    """{변경된 사건번호: [{by, date, name}]} — date_to 이후 선고된 변경 판결은 넣지 않는다."""
    from civil_rag.ingest.build import decision_date

    date_to = config.PREC_DATE_TO if date_to is None else date_to
    result: dict[str, list[dict]] = {}
    scanned = 0
    for path in sorted((prec_dir or config.PREC_DIR).glob("*.json")):
        try:
            raw = path.read_text(encoding="utf-8")
        except OSError:
            continue
        if "변경하기로" not in raw:
            continue
        try:
            prec = json.loads(raw)
        except json.JSONDecodeError:
            continue
        scanned += 1
        d = decision_date(prec)
        if date_to and (not d or d > date_to):
            continue
        own = {norm_case(x) for x in str(prec.get("사건번호") or "").split(",")}
        by = norm_case(str(prec.get("사건번호") or "").split(",")[0])
        for no in overruled_cases_in(prec.get("판례내용") or "", own):
            entry = {"by": by, "date": d, "name": prec.get("사건명") or ""}
            if entry not in result.setdefault(no, []):
                result[no].append(entry)
    return {"date_to": date_to, "scanned": scanned, "overruled": result}


def write_overruled(date_to: str | None = None) -> Path:
    data = build_overruled(date_to)
    path = config.INDEX_DIR / "overruled.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"판례 변경 관계: 변경 판결 {data['scanned']}건 확인 → 변경된 사건 {len(data['overruled'])}건 → {path}")
    return path


def load_overruled() -> dict[str, list[dict]]:
    path = config.INDEX_DIR / "overruled.json"
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8")).get("overruled", {})
    except (OSError, json.JSONDecodeError):
        return {}
