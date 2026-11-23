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
    def find_law(self, name: str, date: str | None = None) -> dict:
        """법령명이 정확히 일치하는 것 중 date(YYYYMMDD) 이전 시행된 가장 최신 버전."""
        res = self._get("lawSearch.do", target="law", query=name, display=100)
        laws = [x for x in _as_list(res.get("LawSearch", {}).get("law")) if x.get("법령명한글") == name]
        if date:
            laws = [x for x in laws if str(x.get("시행일자", "0")) <= date] or laws
        if not laws:
            raise SystemExit(f"'{name}' 을 찾지 못했습니다")
        return max(laws, key=lambda x: str(x.get("시행일자", "")))

    def law_text(self, mst: str) -> str:
        law = self._get("lawService.do", target="law", MST=mst).get("법령", {})
        lines: list[str] = []
        for unit in _as_list(law.get("조문", {}).get("조문단위")):
            content = str(unit.get("조문내용", "")).strip()
            if content:
                lines.append(content)
            if unit.get("조문여부") != "전문":  # 전문 = 편/장/절 제목
                lines.extend(_nested_texts(unit))
        return "\n".join(lines) + "\n"

    # ---------- 판례 ----------
    def search_precs(self, query: str, date_from: str, date_to: str, display: int = 20,
                     court: str | None = "대법원") -> list[dict]:
        """본문 검색(search=2), 선고일자 범위, 최신순."""
        res = self._get("lawSearch.do", target="prec", query=query, search=2, display=display,
                        prncYd=f"{date_from}~{date_to}", sort="ddes")
        items = _as_list(res.get("PrecSearch", {}).get("prec"))
        return [x for x in items if not court or court in str(x.get("법원명", ""))]

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
