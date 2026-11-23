"""국가법령정보센터 Open API (https://open.law.go.kr) 클라이언트.

- 법령: lawSearch.do?target=law → lawService.do?target=law&MST=…
- 판례: lawSearch.do?target=prec → lawService.do?target=prec&ID=…
OC(사용자 ID)는 환경변수 LAW_OC. 응답 필드명은 API 문서 기준이며, 구조가 바뀌면 여기만 고칩니다.
"""

from __future__ import annotations

import json
import os
import time
import urllib.parse
import urllib.request

BASE = "https://www.law.go.kr/DRF"


class LawAPIAuthError(SystemExit):
    pass


class LawAPI:
    def __init__(self, oc: str | None = None, sleep: float = 0.2, retries: int = 3):
        self.oc = oc or os.getenv("LAW_OC")
        if not self.oc:
            raise SystemExit("LAW_OC 환경변수(국가법령정보센터 Open API OC)가 필요합니다 (.env)")
        self.sleep, self.retries = sleep, retries

    def raw(self, endpoint: str, **params) -> str:
        """진단용: 가공 없이 응답 본문."""
        url = f"{BASE}/{endpoint}?" + urllib.parse.urlencode({"OC": self.oc, "type": "JSON", **params})
        with urllib.request.urlopen(url, timeout=60) as r:
            return r.read().decode("utf-8")

    def _get(self, endpoint: str, **params) -> dict:
        url = f"{BASE}/{endpoint}?" + urllib.parse.urlencode({"OC": self.oc, "type": "JSON", **params})
        last: Exception | None = None
        for i in range(self.retries):
            try:
                with urllib.request.urlopen(url, timeout=60) as r:
                    body = r.read().decode("utf-8")
                time.sleep(self.sleep)  # 공공 API 예의상 간격
                data = json.loads(body)
                if isinstance(data, dict) and "result" in data and "실패" in str(data.get("result")):
                    raise LawAPIAuthError(
                        f"law.go.kr 인증 실패: {data.get('result')} {data.get('msg', '')}\n"
                        "→ open.law.go.kr 에 등록한 IP/도메인의 PC 에서 실행하세요 (클라우드·다른 PC 에서는 거부됨).")
                return data
            except LawAPIAuthError:
                raise
            except Exception as e:  # 네트워크/JSON 오류 재시도
                last = e
                time.sleep(2 ** i)
        raise RuntimeError(f"Law API 실패: {endpoint} {params} → {last}")

    # ---------- 법령 ----------
    def law_versions(self, name: str, max_pages: int = 10) -> list[dict]:
        """target=eflaw: 현행 + 연혁(과거 시행) 버전 목록 중 법령명이 정확히 일치하는 것."""
        out: list[dict] = []
        for page in range(1, max_pages + 1):
            res = self._get("lawSearch.do", target="eflaw", query=name, display=100, page=page).get("LawSearch", {})
            items = _as_list(res.get("law"))
            out += [x for x in items if x.get("법령명한글") == name]
            if len(items) < 100 or page * 100 >= int(res.get("totalCnt") or 0):
                break
        return out

    def find_law(self, name: str, date: str | None = None) -> dict:
        """date(YYYYMMDD) 에 시행 중이던 버전 = 시행일자 <= date 중 가장 최신. 없으면 오류."""
        versions = self.law_versions(name)
        if not versions:
            raise SystemExit(f"'{name}' 을 찾지 못했습니다")
        if date:
            eligible = [x for x in versions if str(x.get("시행일자", "99999999")) <= date]
            if not eligible:
                raise SystemExit(f"'{name}': {date} 이전 시행 버전이 검색되지 않았습니다 "
                                 f"(검색된 시행일자: {sorted({str(x.get('시행일자')) for x in versions})})")
            versions = eligible
        return max(versions, key=lambda x: str(x.get("시행일자", "")))

    def law_text(self, mst: str, ef_yd: str | None = None) -> str:
        law = {}
        if ef_yd:  # 연혁 버전은 eflaw 상세로 조회
            law = self._get("lawService.do", target="eflaw", MST=mst, efYd=ef_yd).get("법령", {})
        if not law:
            law = self._get("lawService.do", target="law", MST=mst).get("법령", {})
        lines: list[str] = []
        for unit in _as_list(law.get("조문", {}).get("조문단위")):
            content = str(unit.get("조문내용", "")).strip()
            if content:
                lines.append(content)
            if unit.get("조문여부") != "전문":  # 전문 = 편/장/절 제목
                lines.extend(_nested_texts(unit))
        if not lines:
            raise RuntimeError(f"법령 본문이 비어 있습니다 (MST={mst}, efYd={ef_yd})")
        return "\n".join(lines) + "\n"

    # ---------- 판례 ----------
    def search_precs(self, query: str, date_from: str, date_to: str, want: int = 5,
                     court: str | None = "대법원", max_pages: int = 5, page_size: int = 50) -> list[dict]:
        """본문 검색(search=2, 최신순 응답). 선고일자 범위·법원은 응답을 받아 직접 거름 (API 진단 결과 기준)."""
        out: list[dict] = []
        for page in range(1, max_pages + 1):
            res = self._get("lawSearch.do", target="prec", query=query, search=2,
                            display=page_size, page=page).get("PrecSearch", {})
            items = _as_list(res.get("prec"))
            for x in items:
                d = str(x.get("선고일자", "")).replace(".", "")
                if court and court not in str(x.get("법원명", "")):
                    continue
                if d and date_from <= d <= date_to:
                    out.append(x)
            oldest = min((str(x.get("선고일자", "")).replace(".", "") for x in items), default="0")
            if len(out) >= want or len(items) < page_size or oldest < date_from:
                break
        return out

    def prec(self, prec_id: str) -> dict:
        return self._get("lawService.do", target="prec", ID=prec_id).get("PrecService", {})


def _as_list(x) -> list:
    return x if isinstance(x, list) else ([] if x is None else [x])


def _nested_texts(node) -> list[str]:
    out: list[str] = []
    for key, child in (("항", "항내용"), ("호", "호내용"), ("목", "목내용")):
        for item in _as_list(node.get(key) if isinstance(node, dict) else None):
            if isinstance(item, dict):
                if item.get(child):
                    out.append(str(item[child]).strip())
                out.extend(_nested_texts(item))
    return out
