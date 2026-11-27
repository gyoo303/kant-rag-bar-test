"""v5 방어 기능 (레드팀 공략안 + 구조 분석): 발문 기준 시점, 색인 밖 법령, 진술 간 참조, 인용 문장 대조, 확신도 보정.

모두 순수 함수 + 작은 상태(보정표)라 solver 에서 스위치로 켠다. 문서: docs/analysis/improvement-plan-v5.md
"""

from __future__ import annotations

import json
import re
from pathlib import Path

# ---------- 발문 기준 시점 ("2023. 1. 1. 당시 판례에 의함") ----------
ASOF = re.compile(r"(\d{4})\s*\.\s*(\d{1,2})\s*\.\s*(\d{1,2})\s*\.?\s*(?:현재|당시|기준|시점)")


def asof_date(text: str) -> str | None:
    """발문에 명시된 기준 시점 → YYYYMMDD. 여러 개면 가장 늦은 날짜(보수적으로 그 이후 판례만 제외)."""
    found = [f"{y}{int(m):02d}{int(d):02d}" for y, m, d in ASOF.findall(text or "")]
    return max(found) if found else None


# ---------- 색인 밖 법령 ----------
LAW_BRACKET = re.compile(r"[｢「]([^｣」]{2,40})[｣」]")
# 시험에 자주 나오지만 색인에 없을 수 있는 법령 (괄호 없이 쓰인 경우 대비)
KNOWN_LAWS = (
    "수표법", "이자제한법", "신탁법", "공탁법", "약관의 규제에 관한 법률", "약관규제법", "소액사건심판법",
    "보증인 보호를 위한 특별법", "보증인보호법", "소송촉진 등에 관한 특례법", "주식·사채 등의 전자등록에 관한 법률",
    "전자증권법", "헌법", "상법 시행령", "민사소송규칙", "민사집행규칙", "국가배상법", "자동차손해배상 보장법",
    "제조물 책임법", "할부거래에 관한 법률", "방문판매 등에 관한 법률", "근로기준법", "공증인법",
)


def _norm_law(name: str) -> str:
    return re.sub(r"[\s·ㆍ]", "", name)


def mentioned_laws(text: str) -> list[str]:
    out: dict[str, None] = {}
    for m in LAW_BRACKET.findall(text or ""):
        if m.endswith(("법", "법률", "령", "규칙")):
            out.setdefault(m.strip())
    for law in KNOWN_LAWS:
        if law in (text or ""):
            out.setdefault(law)
    return list(out)


def out_of_corpus(text: str, corpus_titles: set[str]) -> list[str]:
    """진술·발문에 나오는 법령 중 색인에 없는 것 (이름 공백·가운뎃점 무시)."""
    have = {_norm_law(t) for t in corpus_titles}
    aliases = {"약관규제법": "약관의규제에관한법률", "보증인보호법": "보증인보호를위한특별법",
               "전자증권법": "주식사채등의전자등록에관한법률"}
    miss = []
    for law in mentioned_laws(text):
        n = _norm_law(law)
        n = aliases.get(n, n)
        if n not in have:
            miss.append(law)
    return miss


# ---------- 진술 간 참조 ("ㄱ의 경우에 이어", "위 ㄴ에서") ----------
XREF = re.compile(r"(?:위|앞의?|상기)\s*([ㄱ-ㅂ])|([ㄱ-ㅂ])\s*(?:의|에서의?)\s*(?:경우|사안|사실|상황|결론)")


def cross_refs(key: str, statement: str, keys: list[str]) -> list[str]:
    """이 진술이 전제로 삼는 다른 진술 키."""
    out = []
    for a, b in XREF.findall(statement or ""):
        k = a or b
        if k in keys and k != key and k not in out:
            out.append(k)
    return out


# ---------- 인용 문장 대조 ----------
def _squash(s: str) -> str:
    return re.sub(r"[\s\"'“”‘’「」｢｣.,·ㆍ()\[\]]", "", s or "")


def quote_supported(quote: str | None, texts: list[str], min_len: int = 6, mode: str = "strict",
                    min_ratio: float = 0.7) -> bool | None:
    """판단이 근거로 든 인용 문장이 인용한 청크 본문에 실제로 있는가. 인용이 없거나 너무 짧으면 None.

    mode="relaxed" (v6 0-2): "…"·"..." 로 줄인 인용은 조각별로 대조하고, 조각마다 원문과 가장 길게 겹치는 부분을 더해
    인용 길이의 min_ratio 이상이면 일치로 본다 (조사·어미 한두 글자 차이, 생략 인용 허용).
    """
    q = _squash(quote)
    if len(q) < min_len:
        return None
    bodies = [_squash(t) for t in texts]
    if any(q in b for b in bodies):
        return True
    if mode != "relaxed" or not bodies:
        return False
    from difflib import SequenceMatcher

    segs = [x for x in (_squash(p) for p in re.split(r"…|\.\.\.|⋯|~", quote or "")) if x]
    total = sum(len(x) for x in segs) or 1
    for b in bodies:
        hit = 0
        for seg in segs:
            if seg in b:
                hit += len(seg)
                continue
            # 조각과 원문의 공통 부분을 앞에서부터 차례로 (3글자 이상만: 흩어진 한두 글자 일치는 세지 않음)
            sm = SequenceMatcher(None, seg, b, autojunk=False)
            hit += sum(m.size for m in sm.get_matching_blocks() if m.size >= 3)
        if hit / total >= min_ratio:
            return True
    return False


# ---------- 확신도 보정 ----------
def _pav(xs: list[tuple[float, float, int]]) -> list[tuple[float, float]]:
    """(구간 상한, 정답률, 개수) → 정답률이 확신도에 대해 줄지 않도록 이웃 구간 병합 (pool adjacent violators)."""
    blocks = [[ub, acc * n, n] for ub, acc, n in xs if n]
    i = 0
    while i < len(blocks) - 1:
        a, b = blocks[i], blocks[i + 1]
        if a[1] / a[2] > b[1] / b[2]:
            blocks[i] = [b[0], a[1] + b[1], a[2] + b[2]]
            del blocks[i + 1]
            i = max(i - 1, 0)
        else:
            i += 1
    return [(ub, s / n) for ub, s, n in blocks]


def fit_calibration(samples: list[tuple[str, float, bool]], edges: tuple[float, ...] = (0.5, 0.7, 0.8, 0.9, 0.95, 0.99, 1.0),
                    floor: float = 0.55, ceil: float = 0.98) -> dict:
    """(source, 확신도, 정답 여부) 표본 → source 별 단조 보정표. 표본이 적은 source 는 전체 표로."""
    def table(rows):
        bins = []
        lo = 0.0
        for ub in edges:
            sel = [ok for _, c, ok in rows if lo < c <= ub or (lo == 0.0 and c == 0.0)]
            bins.append((ub, (sum(sel) / len(sel)) if sel else 0.0, len(sel)))
            lo = ub
        return [(ub, round(min(max(acc, floor), ceil), 4)) for ub, acc in _pav(bins)]

    out = {"edges": list(edges), "n": len(samples), "all": table(samples)}
    for src in ("evidence", "knowledge"):
        rows = [r for r in samples if r[0] == src]
        if len(rows) >= 30:
            out[src] = table(rows)
    return out


class Calibrator:
    def __init__(self, data: dict):
        self.data = data

    @classmethod
    def load(cls, path: str | Path | None) -> "Calibrator | None":
        if not path:
            return None
        p = Path(path)
        if not p.exists():
            print(f"[warn] 확신도 보정표 없음: {p} → 보정 없이 진행 (`kant-rag calibrate` 로 생성)")
            return None
        return cls(json.loads(p.read_text(encoding="utf-8")))

    def __call__(self, confidence: float, source: str = "evidence") -> float:
        """확신도 → 그 판단이 맞을 확률(보정)."""
        tab = self.data.get(source) or self.data["all"]
        for ub, acc in tab:
            if confidence <= ub:
                return acc
        return tab[-1][1]

    def support(self):
        """choose_answer 에 넘길 support 함수: 보정 확률로 보기 점수 계산 (0점·동점이 잘 생기지 않음)."""
        def f(j, want: bool) -> float:
            if j is None or j.verdict == "unknown":
                return 0.5
            p = self(j.confidence, getattr(j, "source", "evidence"))
            return p if (j.verdict == "true") == want else 1 - p
        return f
