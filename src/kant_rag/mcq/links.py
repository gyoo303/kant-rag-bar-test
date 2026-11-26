"""연결 지도 (개선안 v6 2-1~2-3): 판례 원자료의 참조판례·참조조문으로 근거를 잇는다. 추가 데이터 없음.

색인 청크에는 참조판례가 없고 참조조문은 본문 끝에 붙은 글자일 뿐이라 검색에 거의 쓰이지 않았다.
원자료(data/raw/cases/*.jsonl)의 두 필드로 세 가지 연결을 만든다.

2-1 판례 변경: 참조판례의 "(변경)" 표시 → 변경된 판례(overruled_by)·변경한 판례(overrules)와 선고일.
    근거 머리에 표시하고, 기준 시점 이전에 변경되었으면 변경한 판례를 연결 후보로 올린다.
2-2 조문 → 판례: 참조조문에 그 조문을 적은 판례 항목. 검색된 조문에서 판례로 넘어간다.
2-3 판례 → 판례: 검색된 판례 항목의 참조판례 (같은 법리를 처음 세운 판례 등).

후보는 진술과 리랭커로 대조해 진술당 몇 개만 쓴다 (solver).
"""

from __future__ import annotations

import json
import pickle
import re
from collections import defaultdict
from pathlib import Path

from kant_rag.mcq.context import ART, CASE_ITEM, _art_key

CASE_NO = re.compile(r"\d{2,4}[가-힣]{1,4}\d+")
REF_ENTRY = re.compile(r"(\d{4})\.\s*(\d{1,2})\.\s*(\d{1,2})\.\s*(?:자|선고)?\s*(\d{2,4}[가-힣]{1,4}\d+)")
LABELS = re.compile(r"^\s*((?:\[\d+\]\s*)+)")
SAME_LAW = ("같은 법", "같은법", "동법", "위 법")
CACHE_VERSION = 2


def norm_case_no(case_no: str | None) -> str:
    """'2017스98, 99' → '2017스98' (첫 사건번호)."""
    m = CASE_NO.search(case_no or "")
    return m.group(0) if m else (case_no or "")


def law_key(name: str) -> str:
    return re.sub(r"\s+", "", name or "")


def _groups(text: str) -> list[tuple[list[str], str]]:
    """'[1] A / [2][3] B' → [(['1'], 'A'), (['2','3'], 'B')]. 항목 표시가 없으면 ['*']."""
    out = []
    for g in (text or "").split(" / "):
        m = LABELS.match(g)
        labels = re.findall(r"\d+", m.group(1)) if m else ["*"]
        out.append((labels, g[m.end():] if m else g))
    return out


def parse_ref_cases(text: str) -> list[tuple[list[str], str, str, bool]]:
    """참조판례 → [(항목들, 사건번호, 선고일 YYYYMMDD, 변경 여부)]."""
    out = []
    for labels, g in _groups(text):
        ms = list(REF_ENTRY.finditer(g))
        for i, m in enumerate(ms):
            seg = g[m.end(): ms[i + 1].start() if i + 1 < len(ms) else len(g)]
            d = f"{m.group(1)}{int(m.group(2)):02d}{int(m.group(3)):02d}"
            out.append((labels, m.group(4), d, "(변경)" in seg))
    return out


def _strip_paren(s: str) -> str:
    prev = None
    while prev != s:
        prev, s = s, re.sub(r"\([^()]*\)", "", s)
    return s


def parse_ref_articles(text: str) -> list[tuple[list[str], str, str]]:
    """참조조문 → [(항목들, 법령명, 제N조)]. '민법 제430조, 제431조, 상법 제24조' 처럼 법령명이 이어진다."""
    out = []
    for labels, g in _groups(text):
        cur = ""
        for tok in _strip_paren(g).split(","):
            tok = tok.strip()
            m = ART.search(tok)
            if not m:
                continue
            law = tok[: m.start()].strip()
            law = re.sub(r"^구\s*", "", law)
            if law and not any(law.startswith(x) for x in SAME_LAW):
                cur = law
            if cur:
                out.append((labels, cur, _art_key(m.group(1), m.group(2))))
    return out


class LinkGraph:
    """색인에 있는 판례·조문 청크 사이의 연결. 원자료는 한 번 읽어 index 폴더에 캐시."""

    def __init__(self, chunks_by_id: dict, cases_dir: Path, cache: Path | None = None):
        self.by_id = chunks_by_id
        # 색인의 판례 항목: 사건번호 → 항목 → 청크 ids (조각 포함, 순서대로)
        self.items: dict[str, dict[str, list[str]]] = defaultdict(lambda: defaultdict(list))
        self.decided: dict[str, str] = {}
        self.statutes: dict[tuple[str, str], list[str]] = defaultdict(list)  # (법령명, 제N조) → 청크 ids
        for cid, c in chunks_by_id.items():
            md = c.metadata or {}
            if md.get("doc_type") == "case":
                m = CASE_ITEM.match(cid)
                no = norm_case_no(md.get("case_no"))
                if m and no:
                    self.items[no][m.group(2)].append(cid)
                    self.decided[no] = re.sub(r"\D", "", str(md.get("decided") or ""))
            elif md.get("doc_type") == "statute" and md.get("article"):
                self.statutes[(law_key(c.title), str(md["article"]).split("~")[0])].append(cid)
        raw = self._load_raw(cases_dir, cache)
        self.overruled_by: dict[str, list[tuple[str, str]]] = raw["overruled_by"]
        self.overrules: dict[str, list[tuple[str, str]]] = raw["overrules"]
        self.cites: dict[tuple[str, str], list[str]] = raw["cites"]
        self.by_article: dict[tuple[str, str], list[tuple[str, str]]] = raw["by_article"]

    # ---------- 원자료 ----------
    @staticmethod
    def _signature(cases_dir: Path) -> list:
        return [CACHE_VERSION] + sorted((f.name, f.stat().st_size) for f in cases_dir.glob("*.jsonl"))

    def _load_raw(self, cases_dir: Path, cache: Path | None) -> dict:
        sig = self._signature(cases_dir) if cases_dir.exists() else [CACHE_VERSION]
        if cache is not None and cache.exists():
            try:
                data = pickle.loads(cache.read_bytes())
                if data.get("sig") == sig:
                    return data
            except Exception:
                pass
        data = build_raw_links(cases_dir)
        data["sig"] = sig
        if cache is not None:
            try:
                cache.parent.mkdir(parents=True, exist_ok=True)
                cache.write_bytes(pickle.dumps(data))
            except OSError:
                pass
        return data

    # ---------- 질의 ----------
    def case_no_of(self, cid: str) -> tuple[str, str] | None:
        m = CASE_ITEM.match(cid)
        c = self.by_id.get(cid)
        if not m or c is None:
            return None
        return norm_case_no((c.metadata or {}).get("case_no")), m.group(2)

    def first_chunks(self, case_no: str, items: list[str] | None = None) -> list[str]:
        """판례의 항목별 첫 청크 (items 가 None·'*' 이면 전 항목)."""
        its = self.items.get(case_no, {})
        keys = sorted(its, key=int) if not items or "*" in items else [i for i in items if i in its]
        return [its[i][0] for i in keys if its[i]]

    def overruled_info(self, case_no: str) -> dict:
        """{'overruled_by': [(사건, 선고일)], 'overrules': [(사건, 선고일)]} (없으면 빈 dict)."""
        out = {}
        if self.overruled_by.get(case_no):
            out["overruled_by"] = self.overruled_by[case_no]
        if self.overrules.get(case_no):
            out["overrules"] = self.overrules[case_no]
        return out

    def candidates(self, chunk_ids: list[str], cutoff: str | None = None, max_n: int = 24) -> list[tuple[str, str]]:
        """검색된 청크들에서 연결로 닿는 청크 → [(청크 id, 연결 종류)]. 우선순위: 변경 판례 > 판례→판례 > 조문→판례."""
        have = set(chunk_ids)
        out: dict[str, str] = {}

        def add(ids, kind):
            for x in ids:
                if x in have or x in out:
                    continue
                no = self.case_no_of(x)
                if cutoff and no and self.decided.get(no[0], "") > cutoff:
                    continue
                out[x] = kind

        over, cite, art = [], [], []
        for cid in chunk_ids:
            c = self.by_id.get(cid)
            if c is None:
                continue
            md = c.metadata or {}
            if md.get("doc_type") == "case":
                key = self.case_no_of(cid)
                if not key:
                    continue
                no, item = key
                for new, d in self.overruled_by.get(no, []):
                    if not cutoff or d <= cutoff:
                        over += self.first_chunks(new)
                for ref in self.cites.get((no, item), []) + self.cites.get((no, "*"), []):
                    cite += self.first_chunks(ref)
            elif md.get("doc_type") == "statute" and md.get("article"):
                refs = self.by_article.get((law_key(c.title), str(md["article"]).split("~")[0]), [])
                # 많이 인용된 조문은 최근 판례 우선 (리랭커 후보 상한 때문에)
                refs = sorted(refs, key=lambda x: self.decided.get(x[0], ""), reverse=True)
                for no, item in refs:
                    art += self.first_chunks(no, [item])
        add(over, "overruler")
        add(cite, "cited_case")
        add(art, "article_case")
        return list(out.items())[:max_n]


def build_raw_links(cases_dir: Path) -> dict:
    """원자료 전체를 한 번 읽어 연결 표를 만든다 (색인에 없는 판례도 포함; 질의 때 색인 청크로 거른다)."""
    overruled_by: dict[str, list[tuple[str, str]]] = defaultdict(list)
    overrules: dict[str, list[tuple[str, str]]] = defaultdict(list)
    cites: dict[tuple[str, str], list[str]] = defaultdict(list)
    by_article: dict[tuple[str, str], list[tuple[str, str]]] = defaultdict(list)
    seen: set[str] = set()
    files = sorted(cases_dir.glob("*.jsonl")) if cases_dir.exists() else []
    for f in files:
        for line in f.open(encoding="utf-8"):
            try:
                d = json.loads(line)
            except ValueError:
                continue
            no = norm_case_no(d.get("case_no"))
            if not no or no in seen:
                continue
            seen.add(no)
            decided = re.sub(r"\D", "", str(d.get("decided") or ""))
            for labels, ref, ref_d, changed in parse_ref_cases(d.get("ref_cases") or ""):
                if ref == no:
                    continue
                if changed:  # 이 판결(no)이 ref 를 변경
                    if (no, decided) not in overruled_by[ref]:
                        overruled_by[ref].append((no, decided))
                    if (ref, ref_d) not in overrules[no]:
                        overrules[no].append((ref, ref_d))
                for lb in labels:
                    if ref not in cites[(no, lb)]:
                        cites[(no, lb)].append(ref)
            for labels, law, art in parse_ref_articles(d.get("ref_articles") or ""):
                for lb in labels:
                    by_article[(law_key(law), art)].append((no, lb))
    return {"overruled_by": dict(overruled_by), "overrules": dict(overrules), "cites": dict(cites),
            "by_article": dict(by_article)}
