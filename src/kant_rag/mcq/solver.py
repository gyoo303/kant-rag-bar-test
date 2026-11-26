"""선택형 풀이: 진술별 검색 → LLM 진술 정오 판단 → 규칙으로 정답 번호 결정.

LLM 에게 번호를 직접 고르게 하지 않고, 진술별 판단(verdict)과 발문의 극성/형식(옳은 것/옳지 않은 것,
단일/조합/개수)으로 정답을 계산합니다. 덕분에 '검색 누락 → 진술 판단 오류 → 정답 오류' 를 단계별로 분석할 수 있습니다.
"""

from __future__ import annotations

import re
import threading
import time
from collections import Counter
from pathlib import Path

from kant_rag.config import Settings
from kant_rag.generation.llmcall import call_llm, extract_json
from kant_rag.mcq.parse import parse_combo, parse_ox
from kant_rag.mcq.context import (
    ChunkGraph,
    build_title_index,
    chapter_company,
    chapter_of,
    company_type,
    title_matches,
)
from kant_rag.mcq.defense import Calibrator, asof_date, cross_refs, out_of_corpus, quote_supported
from kant_rag.mcq.prompts import (
    MCQ_CLOSED_SYSTEM,
    MCQ_CLOSED_USER,
    MCQ_FUSION_USER,
    MCQ_REWRITE_SYSTEM,
    MCQ_REWRITE_SYSTEM_V2,
    MCQ_REWRITE_USER,
    MCQ_SYSTEM,
    MCQ_REWRITE_SYSTEM_V3,
    MCQ_SYSTEM_V2,
    MCQ_SYSTEM_V3,
    MCQ_SYSTEM_V4,
    MCQ_SYSTEM_V5,
    MCQ_SYSTEM_V6,
    MCQ_SYSTEM_V7,
    MCQ_RESEARCH_USER,
    MCQ_REWRITE_SYSTEM_V4,
    MCQ_TIEBREAK_USER,
    MCQ_USER,
)
from kant_rag.mcq.links import LinkGraph, norm_case_no
from kant_rag.mcq.schemas import ExamQuestion, StatementJudgment
from kant_rag.retrieval.hybrid import rrf_fuse
from kant_rag.retrieval.pipeline import RetrievalMode, Retriever
from kant_rag.schemas import RetrievedChunk


def statement_query(q: ExamQuestion, statement: str, stem_chars: int) -> str:
    stem = q.stem[:stem_chars]
    return f"{stem}\n{statement}" if stem else statement


def _support(j: StatementJudgment | None, want: bool) -> float:
    """진술이 want(true/false) 일 정도. unknown/누락은 0.5."""
    if j is None or j.verdict == "unknown":
        return 0.5
    p = 0.5 + 0.5 * j.confidence
    return p if (j.verdict == "true") == want else 1 - p


def choose_answer(q: ExamQuestion, judgments: dict[str, StatementJudgment],
                  support=None) -> tuple[int | None, dict[int, float]]:
    """진술 판단 → 보기별 점수 → 최고점 보기. 모든 판단이 unknown 이면 None (근거 부족)."""
    _support = support or globals()["_support"]
    if not judgments or all(j.verdict == "unknown" for j in judgments.values()):
        return None, {}
    target = q.polarity == "correct"  # '옳은 것' 을 찾는가
    scores: dict[int, float] = {}
    if q.form == "single":
        for n in q.options:
            scores[n] = _support(judgments.get(str(n)), target)
    elif q.form == "combination":
        for n, text in q.options.items():
            chosen = parse_combo(text)
            # 고른 진술은 target, 고르지 않은 진술은 반대여야 함 → 로그 우도 대신 곱의 평균
            s = 1.0
            for key in q.items:
                s *= _support(judgments.get(key), target if key in chosen else not target)
            scores[n] = s
    elif q.form == "blank":  # 괄호 넣기형: 보기의 값 조합이 모두 참일 정도
        cands = {lv: k for k, lv in q.blank_candidates().items()}
        for n, fill in q.blanks.items():
            s = 1.0
            for letter, v in fill.items():
                s *= _support(judgments.get(cands.get((letter, v), "")), True)
            scores[n] = s
    elif q.form == "ox":
        for n, text in q.options.items():
            labels = parse_ox(text)
            s = 1.0
            for key in q.items:
                s *= _support(judgments.get(key), labels[key]) if key in labels else 0.5
            scores[n] = s
    else:  # count
        expected = sum(_support(judgments.get(k), target) for k in q.items)
        for n, text in q.options.items():
            m = re.search(r"(\d+)", text)
            scores[n] = -abs(int(m.group(1)) - expected) if m else float("-inf")
    best = max(scores, key=lambda n: (scores[n], -n))
    return best, scores


CIRCLED_NUM = "①②③④⑤"


def tied_options(scores: dict, eps: float = 1e-9, ratio: float = 1.0) -> list[int]:
    """최고점(>0)과 같은(ratio<1 이면 최고점×ratio 이상인) 보기들. 해당 없으면 길이 1 이하."""
    if not scores:
        return []
    top = max(scores.values())
    if top <= 0 or top == float("inf"):
        return []
    if ratio >= 1.0:
        return sorted(int(n) for n, v in scores.items() if abs(v - top) <= eps)
    return sorted(int(n) for n, v in scores.items() if v >= top * ratio - eps)


def exact_match_exists(q: ExamQuestion, judgments: dict[str, StatementJudgment]) -> bool:
    """단정한 진술 판단과 완전히 맞는 보기가 있는가 (없으면 '판단 불일치')."""
    if q.form == "count":
        return True
    for n in q.options:
        req = _required(q, n)
        if all(j.verdict == "unknown" or k not in req or (j.verdict == "true") == req[k]
               for k, j in judgments.items()):
            return True
    return False


def _capped_support(cap: float):
    def f(j: StatementJudgment | None, want: bool) -> float:
        if j is None or j.verdict == "unknown":
            return 0.5
        p = 0.5 + 0.5 * min(j.confidence, cap)
        return p if (j.verdict == "true") == want else 1 - p
    return f


def _required(q: ExamQuestion, n: int) -> dict[str, bool]:
    """보기 n 이 정답이려면 각 진술이 가져야 할 참/거짓."""
    target = q.polarity == "correct"
    text = q.options[n]
    if q.form == "single":
        return {str(n): target}
    if q.form == "combination":
        chosen = parse_combo(text)
        return {k: (target if k in chosen else not target) for k in q.items}
    if q.form == "ox":
        return parse_ox(text)
    if q.form == "blank":
        fill = q.blanks.get(n, {})
        return {k: fill.get(letter) == v for k, (letter, v) in q.blank_candidates().items()}
    return {}


def choose_answer_robust(q: ExamQuestion, judgments: dict[str, StatementJudgment],
                         cap: float = 0.95) -> tuple[int | None, dict[int, float], dict]:
    """choose_answer + 예비 규칙(개선안 B-계산).

    진술 판단 조합이 어느 보기와도 맞지 않아 모든 보기가 0점이면(확신도 1.0 판단끼리 충돌),
    확신도 상한(cap)을 두고 다시 계산해 '가장 적게·가장 약하게 뒤집으면 맞는 보기'를 고른다.
    이때 info.inconsistent=True 와 뒤집힌 진술(flipped)을 남긴다. 평소(최고점>0)에는 choose_answer 와 같다.
    """
    best, scores = choose_answer(q, judgments)
    info: dict = {"inconsistent": False, "flipped": []}
    if best is None or q.form == "count" or not scores or max(scores.values()) > 0:
        return best, scores, info
    best, scores = choose_answer(q, judgments, support=_capped_support(cap))
    req = _required(q, best)
    flipped = [k for k, want in req.items()
               if (j := judgments.get(k)) is not None and j.verdict != "unknown" and (j.verdict == "true") != want]
    info = {"inconsistent": True, "flipped": flipped, "cap": cap}
    return best, scores, info


def _text(msg) -> str:
    c = msg.content
    return c if isinstance(c, str) else "".join(
        b.get("text", "") for b in c if isinstance(b, dict) and b.get("type") == "text")


def rewrite_statement_queries(q: ExamQuestion, settings: Settings) -> tuple[dict[str, list[str]], dict]:
    """진술별 검색 질의 생성 (문항당 LLM 1회). 정답·근거는 입력하지 않음. 실패/이상 키는 원래 질의로 fallback.

    rewrite_queries=2 이면 진술마다 쟁점(issue)·예외(exception) 질의 2개 (개선안 A2).
    """
    c = settings.mcq
    multi = c.rewrite_queries >= 2
    statements = q.statements()
    original = {k: statement_query(q, v, c.stem_chars_in_query) for k, v in statements.items()}
    v3 = multi and c.rewrite_version in ("v3", "v4")
    if multi and c.rewrite_version == "v4":
        system, label = MCQ_REWRITE_SYSTEM_V4, "v4-facts"
    elif v3:
        system, label = MCQ_REWRITE_SYSTEM_V3, "v3-party"
    else:
        system, label = (MCQ_REWRITE_SYSTEM_V2, "v2-multi") if multi else (MCQ_REWRITE_SYSTEM, "v1")
    stem_chars = (c.rewrite_stem_chars or len(q.stem)) if v3 else c.stem_chars_in_query  # 0 = 발문 전체
    info: dict = {"original": original, "rewritten": {}, "fallback_keys": [], "error": None, "prompt": label}
    try:
        listing = "\n".join(f"{k}. {v}" for k, v in statements.items())
        raw, calls = call_llm(settings.models.llm_provider, settings.models.llm_model,
                              [("system", system),
                               ("human", MCQ_REWRITE_USER.format(stem=q.stem[:stem_chars],
                                                                 statements=listing))], c.rewrite_max_tokens)
        info["llm_calls"] = calls
        info["raw"] = (raw or "")[:4000]  # 0-1 전부 fallback 일 때 원인 확인용
        data = extract_json(raw)
    except Exception as e:
        data = {}
        info["error"] = f"{type(e).__name__}: {e}"
    if c.rewrite_key_normalize and isinstance(data, dict):  # 0-1 "①"·"1."·"보기 1" → "1"
        data = {**{_norm_key(k, list(statements)): v for k, v in data.items()}, **{k: v for k, v in data.items() if k in statements}}
    queries: dict[str, list[str]] = {}
    for k in statements:
        v = data.get(k)
        if isinstance(v, dict):
            v = [v.get("issue"), v.get("exception"), v.get("party")]
        cand = [x.strip() for x in (v if isinstance(v, list) else [v]) if isinstance(x, str) and 2 <= len(x.strip()) <= 300]
        if cand:
            queries[k] = cand[: max(1, c.rewrite_queries)]
        else:
            queries[k] = [original[k]]
            info["fallback_keys"].append(k)
    info["rewritten"] = queries
    if statements and len(info["fallback_keys"]) == len(statements) and not info["error"]:
        info["error"] = "all_fallback: 리라이트 출력에서 진술 키를 찾지 못함 (raw 참고)"
    return queries, info


def _norm_key(k, keys: list[str]) -> str:
    """리라이트·판단 출력의 진술 키 표기 차이를 흡수: '①'·'1.'·'(1)'·'보기 1'·'ㄱ.' → '1'·'ㄱ'."""
    s = str(k).strip()
    s = re.sub(r"^(보기|진술|지문|선지)\s*", "", s)
    s = s.strip(" .:)(）（[]")
    if s and s[0] in CIRCLED_NUM:
        s = str(CIRCLED_NUM.index(s[0]) + 1)
    return s if s in keys else str(k)


def _parse_judgments(raw: str, keys: list[str]) -> dict[str, StatementJudgment]:
    data = extract_json(raw, "judgments").get("judgments", {})
    return {k: StatementJudgment.model_validate(data[k]) for k in keys if k in data}


FULL_COURT_MARKS = ("[다수의견]", "[대법관", "[별개의견]", "[반대의견]")


def _case_attrs(chunk, full_court: set[str] | None) -> str:
    """판례 근거의 선고일·전원합의체 여부 (개선안 v4 case_meta). 조문이면 빈 문자열."""
    md = chunk.metadata or {}
    if md.get("doc_type") != "case":
        return ""
    d = re.sub(r"\D", "", str(md.get("decided") or ""))
    out = f' decided="{d[:4]}-{d[4:6]}-{d[6:8]}"' if len(d) == 8 else ""
    if full_court is not None and md.get("case_no") in full_court:
        out += ' full_court="true"'
    return out


def _doc(cid: str, chunk, text: str, kind: str | None = None, meta: set[str] | None | bool = False,
         attrs: str = "") -> str:
    k = f' kind="{kind}"' if kind else ""
    extra = _case_attrs(chunk, meta if isinstance(meta, set) else None) if meta is not False else ""
    return f'<doc id="{cid}" title="{chunk.title}" loc="{chunk.location()}"{k}{extra}{attrs}>\n{text}\n</doc>'


def _fmt_date(d: str) -> str:
    return f"{d[:4]}-{d[4:6]}-{d[6:8]}" if len(d or "") == 8 else (d or "")


def full_court_cases(chunks_by_id: dict) -> set[str]:
    """판결요지에 다수의견·반대의견 등이 있는 판례 = 전원합의체 (사건번호 집합)."""
    out: set[str] = set()
    for c in chunks_by_id.values():
        md = c.metadata or {}
        if md.get("doc_type") == "case" and any(m in c.text for m in FULL_COURT_MARKS):
            out.add(md.get("case_no"))
    return out


def build_context(per_statement: dict[str, list[RetrievedChunk]], c, graph: ChunkGraph | None,
                  full_court: set[str] | None = None, links: list[tuple[str, str]] | None = None,
                  annotate=None) -> tuple[str, list[str], dict]:
    """진술당 상위 k 근거(중복 제거) + 개선안 A3(같은 판결 다른 항목)·A4(준용 조문) 확장.

    v6: links = 연결 근거 [(청크 id, 연결 종류)] (kind="link"), annotate(chunk) = 판례 변경 표시 속성,
    merge_case_pieces 이면 판결요지 조각을 항목 전체로 합쳐 한 블록으로 (조각 ids 는 모두 used 에).
    """
    seen: dict[str, RetrievedChunk] = {}
    for results in per_statement.values():  # 진술 순서대로, 진술당 상위 k 개
        for r in results[: c.per_statement_k]:
            seen.setdefault(r.chunk.chunk_id, r)
    merge = graph is not None and getattr(c, "merge_case_pieces", False)
    meta = (full_court if full_court is not None else None) if c.case_meta else False
    parts, used, total = [], [], 0
    covered: set[str] = set()
    info: dict = {"siblings": [], "references": []}

    def add(cid, chunk, kind=None, text=None, primary=False) -> bool:
        nonlocal total
        if cid in covered:
            return False
        ids = graph.item_pieces(cid) if merge and text is None else [cid]
        if any(x in covered for x in ids):
            return False
        body = text if text is not None else (graph.item_text(cid) if merge else chunk.text)
        block = _doc(cid, chunk, body, kind, meta=meta, attrs=annotate(chunk) if annotate else "")
        if total + len(block) > c.max_context_chars and (used or not primary):
            return None if primary else False
        parts.append(block)
        for x in ids:
            covered.add(x)
            if x not in used:
                used.append(x)
        total += len(block)
        if len(ids) > 1:
            info.setdefault("merged", []).append(cid)
        return True

    for cid, r in seen.items():
        if add(cid, r.chunk, primary=True) is None:
            break
    if links and graph is not None:
        by_id = graph.by_id
        for cid, kind in links:
            ch = by_id.get(cid)
            if ch is not None and add(cid, ch, "link"):
                info.setdefault("links", []).append(cid)
    if graph is not None:
        extra: list[tuple[str, str | None, str]] = []  # (id, text, kind)
        if c.expand_references:
            extra += [(x, None, "reference") for x in graph.expand_references(used, c.max_expansions)]
        if getattr(c, "statute_parts", False):
            extra += [(x, None, "part") for x in graph.statute_parts(used, c.max_statute_parts)]
        if c.sibling_items:
            extra += [(x, t, "sibling") for x, t in graph.case_siblings(used, max_total=c.max_siblings)]
        for cid, text, kind in extra:
            ch = graph.by_id[cid]
            if add(cid, ch, kind, text=text if text is not None else ch.text):
                info.setdefault({"reference": "references", "sibling": "siblings", "part": "statute_parts"}[kind], []).append(cid)
    return "\n\n".join(parts), used, info


def _stance_conflict(j: StatementJudgment) -> bool:
    """③ 인용이 진술을 지지하는데 거짓, 반박하는데 참으로 판단."""
    st = (j.stance or "").strip().lower()
    return (st == "supports" and j.verdict == "false") or (st == "contradicts" and j.verdict == "true")


def _keep_in_top(results: list[RetrievedChunk], must: list[RetrievedChunk], k: int):
    """② must 청크가 results 상위 k 안에 없으면 상위 k 의 뒤쪽(must 가 아닌 것)과 바꿔 넣는다."""
    must_ids = [r.chunk.chunk_id for r in must]
    top, rest = list(results[:k]), list(results[k:])
    kept = []
    for m in must:
        cid = m.chunk.chunk_id
        if any(r.chunk.chunk_id == cid for r in top):
            continue
        rest = [r for r in rest if r.chunk.chunk_id != cid]
        idx = next((i for i in range(len(top) - 1, -1, -1) if top[i].chunk.chunk_id not in must_ids), None)
        if idx is None:
            break
        rest.insert(0, top[idx])
        top[idx] = m
        kept.append(cid)
    return top + rest, kept


def _type_balance(per_statement: dict[str, list[RetrievedChunk]], k: int):
    """3-3 진술 상위 k 근거가 모두 판례이면 순위 밖에서 가장 높은 조문을 k 번째 자리로 올린다."""
    out, moved = {}, {}
    for key, rs in per_statement.items():
        top = rs[:k]
        if not top or any((r.chunk.metadata or {}).get("doc_type") == "statute" for r in top):
            out[key] = rs
            continue
        idx = next((i for i, r in enumerate(rs[k:], start=k) if (r.chunk.metadata or {}).get("doc_type") == "statute"), None)
        if idx is None:
            out[key] = rs
            continue
        out[key] = rs[: k - 1] + [rs[idx]] + [r for i, r in enumerate(rs[k - 1:], start=k - 1) if i != idx]
        moved[key] = rs[idx].chunk.chunk_id
    return out, moved


class MCQSolver:
    def __init__(self, settings: Settings, retriever: Retriever | None = None):
        self.s = settings
        self._retriever = retriever
        self._lock = threading.RLock()  # A-4 병렬 풀이: GPU 검색·리랭커와 지연 생성은 한 번에 하나만

    def warmup(self) -> None:
        """병렬 풀이 전에 색인·관계 지도·연결 지도 등을 미리 만든다."""
        _ = (self.retriever, self.graph, self.full_court, self.link_graph)
        if self.s.mcq.title_search:
            _ = self.title_index
        if self.s.mcq.out_of_corpus_warn:
            _ = self.corpus_titles

    def _retrieve(self, query: str, mode: RetrievalMode, cutoff: str | None):
        with self._lock:
            return self.retriever.retrieve(query, mode, cutoff) if cutoff else self.retriever.retrieve(query, mode)

    @property
    def retriever(self) -> Retriever:  # closed-book 만 돌릴 때는 색인을 읽지 않음
        if self._retriever is None:
            self._retriever = Retriever(self.s)
        return self._retriever

    @property
    def graph(self) -> ChunkGraph | None:  # A3·A4 를 켰을 때만 생성
        c = self.s.mcq
        if not (c.sibling_items or c.expand_references or c.statute_parts or c.links or c.reverse_usage
                or c.merge_case_pieces or c.chapter_check or c.title_search):
            return None
        with self._lock:
            if getattr(self, "_graph", None) is None:
                self._graph = ChunkGraph(self.retriever.vector.chunks_by_id)
        return self._graph

    @property
    def title_index(self) -> list[tuple[str, str]]:  # M2
        with self._lock:
            if getattr(self, "_titles_idx", None) is None:
                self._titles_idx = build_title_index(self.retriever.vector.chunks_by_id)
        return self._titles_idx

    @property
    def link_graph(self) -> LinkGraph | None:  # v6 2-1~2-3: links 를 켰을 때만 (원자료 한 번 읽고 index 폴더에 캐시)
        if not self.s.mcq.links:
            return None
        with self._lock:
            if getattr(self, "_links", None) is None:
                self._links = LinkGraph(self.retriever.vector.chunks_by_id, self.s.raw_path("cases"),
                                        cache=self.s.index_path() / "links.pkl")
        return self._links

    @property
    def full_court(self) -> set[str] | None:  # case_meta 를 켰을 때만 계산
        if not (self.s.mcq.case_meta or self.s.mcq.recency_boost):
            return None
        with self._lock:
            if getattr(self, "_full_court", None) is None:
                self._full_court = full_court_cases(self.retriever.vector.chunks_by_id)
        return self._full_court

    def solve(self, q: ExamQuestion, mode: RetrievalMode = RetrievalMode.C, run_id: str | None = None) -> dict:
        """정답(q.answer)은 입력에 쓰지 않습니다. 반환값은 실행 기록(record)."""
        c = self.s.mcq
        t0 = time.perf_counter()
        statements = q.statements()
        rec: dict = {
            "run_id": run_id, "question_id": q.id, "number": q.number, "config": mode.value,
            "form": q.form, "polarity": q.polarity, "versions": self.s.versions.model_dump(),
            "models": self.s.models.model_dump(), "settings_fingerprint": self.s.fingerprint(),
            "timing_ms": {}, "status": "ok", "error": None,
        }

        listing = "\n".join(f"{k}. {v}" for k, v in statements.items())
        if mode == RetrievalMode.NONE:
            return self._judge(q, rec, t0, MCQ_CLOSED_SYSTEM,
                               MCQ_CLOSED_USER.format(stem=q.stem, statements=listing, keys=", ".join(statements)),
                               used=[])

        if self.s.optimization.rewrite.enabled:
            t = time.perf_counter()
            queries, rec["rewrite"] = rewrite_statement_queries(q, self.s)
            rec["timing_ms"]["rewrite"] = round((time.perf_counter() - t) * 1000, 1)
        else:
            queries = {k: [statement_query(q, v, c.stem_chars_in_query)] for k, v in statements.items()}
        if c.original_query:  # 리라이트 표현에 따라 결정적 근거를 놓치지 않도록 진술 원문도 검색
            queries = {k: v + ([statements[k]] if statements[k] not in v else []) for k, v in queries.items()}
        if c.cross_ref_queries:  # 다른 진술을 전제로 하는 진술: 전제 진술 + 이 진술을 합친 질의 추가 (v5)
            keys = list(statements)
            refs = {k: cross_refs(k, statements[k], keys) for k in keys}
            refs = {k: v for k, v in refs.items() if v}
            for k, rs in refs.items():
                queries[k] = queries[k] + [" ".join(statements[r] for r in rs) + " " + statements[k]]
            if refs:
                rec["cross_refs"] = refs
        cutoff = asof_date(q.stem) if c.asof_from_stem else None  # 발문 기준 시점 이후 판례 제외 (v5)
        if not cutoff and c.asof_default:  # 발문에 날짜가 없는 과거 시험: 시험 기준일 (v6)
            cutoff = re.sub(r"\D", "", str(c.asof_default))
            rec["asof_source"] = "default"
        if cutoff:
            rec["asof"] = cutoff
        rec["search_queries"] = queries

        t = time.perf_counter()
        per_statement: dict[str, list[RetrievedChunk]] = {}
        rec["retrieval"] = {}
        try:
            for key in statements:
                finals = [self._retrieve(qq, mode, cutoff)["final"] for qq in queries[key]]
                if len(finals) == 1:
                    per_statement[key] = finals[0]
                else:  # 쟁점·예외 질의 결과를 순위로 결합 (RRF)
                    per_statement[key] = rrf_fuse({f"q{i}": f for i, f in enumerate(finals)},
                                                  rrf_k=self.s.retrieval.rrf_k, top_k=self.s.retrieval.final_k)
                    if c.original_keep and statements[key] in queries[key]:  # ② 원문 질의 상위 결과 보장
                        orig = finals[queries[key].index(statements[key])][: c.original_keep]
                        per_statement[key], kept = _keep_in_top(per_statement[key], orig, c.per_statement_k)
                        if kept:
                            rec.setdefault("original_kept", {})[key] = kept
                rec["retrieval"][key] = [
                    {"rank": r.rank, "chunk_id": r.chunk.chunk_id, "score": r.score, **r.trace}
                    for r in per_statement[key]
                ]
        except Exception as e:
            rec.update(status="retrieval_error", error=f"{type(e).__name__}: {e}", predicted=None)
            rec["timing_ms"]["total"] = round((time.perf_counter() - t0) * 1000, 1)
            return rec
        if c.recency_boost:  # 3-6 전원합의체·최근 판례 가산
            per_statement = {k: self._boost(v) for k, v in per_statement.items()}
        if c.type_balance:  # 3-3 진술 근거에 조문이 없으면 순위 밖 조문 1개를 k 번째로
            per_statement, rec["type_balance"] = _type_balance(per_statement, c.per_statement_k)
        links = None
        if c.links or c.reverse_usage or c.chapter_check or c.title_search:  # 2-1~2-4·M1·M2 연결 근거
            try:
                links = self._link_stage(per_statement, statements, cutoff, rec, q.stem)
            except Exception as e:  # 연결 실패는 풀이를 막지 않음
                rec["links"] = {"error": f"{type(e).__name__}: {e}"}
        rec["timing_ms"]["retrieval"] = round((time.perf_counter() - t) * 1000, 1)

        annotate = self._annotator(cutoff) if (c.links or c.chapter_check) else None
        evidence, used, exp = build_context(per_statement, c, self.graph, self.full_court, links, annotate)
        rec["context_chunk_ids"] = used
        rec["context_expansions"] = exp
        rec["prompt_version"] = c.prompt_version
        system = {"v2": MCQ_SYSTEM_V2, "v3": MCQ_SYSTEM_V3, "v4": MCQ_SYSTEM_V4,
                  "v5": MCQ_SYSTEM_V5, "v6": MCQ_SYSTEM_V6, "v7": MCQ_SYSTEM_V7}.get(c.prompt_version, MCQ_SYSTEM)
        user = MCQ_USER.format(evidence=evidence, stem=q.stem, statements=listing, keys=", ".join(statements))
        if c.out_of_corpus_warn:  # 색인에 없는 법령이 쟁점이면 판단 입력에 경고 (v5)
            miss = out_of_corpus(q.stem + "\n" + listing, self.corpus_titles)
            if miss:
                rec["out_of_corpus"] = miss
                user = f"[색인 밖 법령] 다음 법령은 근거 자료에 없습니다: {', '.join(miss)}\n\n" + user
        rec = self._judge(q, rec, t0, system, user, used)
        if c.no_evidence_penalty < 1.0 and rec.get("judgments") is not None:
            rec = self._flag_no_evidence(q, rec, used)
        if c.quote_check and rec.get("judgments") is not None:
            rec = self._check_quotes(q, rec)
        if c.cite_relevance and rec.get("judgments") is not None:
            rec = self._cite_check(q, rec)
        if c.research and rec.get("judgments") is not None:
            rec = self._research(q, rec, t0, system, evidence, used, mode, cutoff, annotate)
        if c.fusion == "fill_unknown" and rec.get("judgments") is not None:
            rec = self._fuse(q, rec, t0)
        if c.tie_rejudge and rec.get("judgments") is not None:
            rec = self._tiebreak(q, rec, t0, system, evidence, used)
        return rec

    # ---------- v6 ----------
    def _boost(self, rs: list[RetrievedChunk]) -> list[RetrievedChunk]:
        """3-6 같은 쟁점 판례가 여럿이면 전원합의체·최근(10년 이내) 판례를 위로 (점수 × (1+boost))."""
        b = self.s.mcq.recency_boost
        fc = self.full_court or set()
        recent = str(int(time.strftime("%Y")) - 10)

        def w(r):
            md = r.chunk.metadata or {}
            if md.get("doc_type") != "case":
                return 1.0
            x = 1.0 + (b if md.get("case_no") in fc else 0.0)
            return x + (b / 2 if str(md.get("decided") or "")[:4] >= recent else 0.0)
        return sorted(rs, key=lambda r: -r.score * w(r))

    def _annotator(self, cutoff: str | None):
        """2-1 판례 근거 머리에 변경 관계 표시: overruled_by="사건(선고일)", overrules="사건"."""
        lg = self.link_graph
        chapters = self.s.mcq.chapter_check
        hide = self.s.mcq.hide_future
        if lg is None and not chapters:
            return None

        def ann(chunk) -> str:
            md = chunk.metadata or {}
            if md.get("doc_type") == "statute" and chapters:  # M1 조문 위치
                ch = chapter_of(chunk)
                return f' chapter="{ch}"' if ch else ""
            if md.get("doc_type") != "case" or lg is None:
                return ""
            info = lg.overruled_info(norm_case_no(md.get("case_no")))
            if cutoff and hide:  # 과거 시험 검증: 기준 시점 뒤의 판례는 이름도 보여주지 않음
                info = {k: [(n, d) for n, d in v if d <= cutoff] for k, v in info.items()}
                info = {k: v for k, v in info.items() if v}
            out = ""
            if info.get("overruled_by"):
                xs = info["overruled_by"]
                out += ' overruled_by="' + ", ".join(f"{n}({_fmt_date(d)})" for n, d in xs) + '"'
                if cutoff and all(d > cutoff for _, d in xs):
                    out += ' overruled_after_asof="true"'
            if info.get("overrules"):
                out += ' overrules="' + ", ".join(n for n, _ in info["overrules"]) + '"'
            return out
        return ann

    def _link_stage(self, per_statement: dict[str, list[RetrievedChunk]], statements: dict[str, str],
                    cutoff: str | None, rec: dict, stem: str = "") -> list[tuple[str, str]]:
        """2-1~2-4·M1·M2 진술별 상위 근거에서 연결로 닿는 후보 → 진술과 리랭커로 대조 → 진술당 link_k 개.

        반드시 넣는 것(점수 무관, 가장 관련 높은 하나): 변경한 판례(overruler), 회사 종류가 다른 장의 조문을
        진술의 회사 종류 장에서 준용하는 조문(chapter_user)."""
        c = self.s.mcq
        by_id = self.retriever.vector.chunks_by_id
        primary = {r.chunk.chunk_id for rs in per_statement.values() for r in rs[: c.per_statement_k]}
        chosen: dict[str, str] = {}
        detail: dict = {}
        for key, results in per_statement.items():
            ids = [r.chunk.chunk_id for r in results[: c.per_statement_k]]
            cands: dict[str, str] = {}
            if self.link_graph is not None:
                for x, kind in self.link_graph.candidates(ids, cutoff, c.link_candidates):
                    cands.setdefault(x, kind)
            if c.chapter_check and self.graph is not None:  # M1 진술은 주식회사인데 근거는 합명회사 장 → 준용 조문
                want = company_type(statements[key]) or company_type(stem)
                for x in ids if want else []:
                    ch = by_id.get(x)
                    have_ct = chapter_company(ch) if ch is not None and (ch.metadata or {}).get("doc_type") == "statute" else None
                    if have_ct and have_ct != want:
                        for u in self.graph.statute_users([x]):
                            if chapter_company(by_id[u]) == want:
                                cands[u] = "chapter_user"
            if c.reverse_usage and self.graph is not None:
                for x in self.graph.statute_users(ids):
                    cands.setdefault(x, "statute_user")
            if c.title_search:  # M2 조문 제목이 진술에 그대로 있으면
                for x in title_matches(statements[key], self.title_index):
                    cands.setdefault(x, "title")
            cands = {x: k for x, k in cands.items() if x in by_id and x not in primary and x not in chosen}
            cands = dict(list(cands.items())[: c.link_candidates])
            if not cands:
                continue
            rcs = [RetrievedChunk(chunk=by_id[x], score=0.0, rank=i + 1, source="rerank")
                   for i, (x, k) in enumerate(cands.items())]
            reranker = getattr(self.retriever, "reranker", None)
            if reranker is not None:
                with self._lock:
                    ranked = reranker.rerank(statements[key], rcs, len(rcs))
            else:
                ranked = [r.model_copy(update={"score": 1.0}) for r in rcs]
            picked = [r.chunk.chunk_id for r in ranked if r.score >= c.link_min_score][: c.link_k]
            for must in ("overruler", "chapter_user"):  # 점수와 상관없이 가장 관련 높은 하나
                hit = [r.chunk.chunk_id for r in ranked if cands[r.chunk.chunk_id] == must]
                if hit and hit[0] not in picked:
                    picked.append(hit[0])
            for x in picked:
                chosen.setdefault(x, cands[x])
            detail[key] = [{"chunk_id": r.chunk.chunk_id, "kind": cands[r.chunk.chunk_id], "score": round(r.score, 4),
                            "picked": r.chunk.chunk_id in picked} for r in ranked[: c.link_k + 3]]
        rec["links"] = {"chosen": chosen, "candidates": detail}
        return list(chosen.items())

    def _cite_check(self, q: ExamQuestion, rec: dict) -> dict:
        """① 판단이 인용한 청크가 그 진술에 맞는 근거인지: (진술, 인용 청크) 리랭커 최고 점수 + 그 진술 검색 결과에 있는지."""
        c = self.s.mcq
        by_id = self.retriever.vector.chunks_by_id
        statements = q.statements()
        reranker = getattr(self.retriever, "reranker", None)
        out: dict = {}
        for k, jd in (rec.get("judgments") or {}).items():
            if jd.get("verdict") == "unknown" or k not in statements:
                continue
            cited = [x for x in jd.get("cited_chunk_ids") or [] if x in by_id]
            own = {x["chunk_id"] for x in (rec.get("retrieval") or {}).get(k, [])}
            in_own = any(x in own for x in cited)
            score = None
            if cited and reranker is not None:
                cands = [RetrievedChunk(chunk=by_id[x], score=0.0, rank=i + 1, source="rerank")
                         for i, x in enumerate(cited)]
                with self._lock:
                    score = max(r.score for r in reranker.rerank(statements[k], cands, len(cands)))
            # 인용이 없거나, 진술과의 관련도가 낮거나, 이 진술 검색 결과 밖 문서인데 관련도도 중간 이하면 약함
            weak = not cited or (score is not None and (score < c.cite_min_score or (not in_own and score < 0.5)))
            out[k] = {"score": None if score is None else round(score, 4), "in_own": in_own, "weak": weak}
        rec["cite_check"] = out
        return rec

    def _cited_texts(self, ids: list[str]) -> list[str]:
        """인용 청크 본문 (조각을 합쳐 전달했으면 항목 전체)."""
        by_id = self.retriever.vector.chunks_by_id
        g = self.graph if self.s.mcq.merge_case_pieces else None
        out = []
        for x in ids:
            if x in by_id:
                out.append(g.item_text(x) if g is not None else by_id[x].text)
        return out

    def _quote_ok(self, j: StatementJudgment) -> bool | None:
        c = self.s.mcq
        return quote_supported(j.quote, self._cited_texts(j.cited_chunk_ids), mode=c.quote_match,
                               min_ratio=c.quote_min_ratio)

    def _flag_no_evidence(self, q: ExamQuestion, rec: dict, used: list[str]) -> dict:
        """4-3 근거 판단인데 유효한 인용 청크가 하나도 없으면 표시하고 확신도 × no_evidence_penalty."""
        c = self.s.mcq
        have = set(used)
        judgments = {k: StatementJudgment.model_validate(v) for k, v in rec["judgments"].items()}
        flagged = [k for k, j in judgments.items() if j.verdict != "unknown" and j.source == "evidence"
                   and not any(x in have for x in j.cited_chunk_ids)]
        rec["no_evidence"] = flagged
        if flagged:
            for k in flagged:
                j = judgments[k]
                judgments[k] = j.model_copy(update={"confidence": round(j.confidence * c.no_evidence_penalty, 3)})
            predicted, scores, chk = self._choose(q, judgments)
            rec.update(judgments={k: j.model_dump() for k, j in judgments.items()}, option_scores=scores,
                       predicted=predicted, answer_check=chk)
        return rec

    def _decisive(self, q: ExamQuestion, judgments: dict[str, StatementJudgment], predicted: int,
                  max_n: int = 2) -> list[str]:
        """3-2 판단을 뒤집으면 정답이 바뀌는 고확신(≥0.9) 진술."""
        out = []
        for k, j in judgments.items():
            if j.verdict == "unknown" or j.confidence < 0.9:
                continue
            flip = {**judgments, k: j.model_copy(update={"verdict": "false" if j.verdict == "true" else "true"})}
            if choose_answer(q, flip)[0] != predicted:
                out.append(k)
        return sorted(out, key=lambda k: judgments[k].confidence)[:max_n]

    def _research(self, q: ExamQuestion, rec: dict, t0: float, system: str, evidence: str, used: list[str],
                  mode: RetrievalMode, cutoff: str | None, annotate) -> dict:
        """3-1 다시 찾는 검색: 유보·저확신·인용 불일치·근소 차 진술만 missing(또는 풀어 쓴 진술)로 2차 검색,
        이미 본 근거를 뺀 새 근거와 함께 그 진술만 재판단. 새 판단은 인용이 확인되고 확신도가 같거나 높을 때만 채택."""
        c = self.s.mcq
        statements = q.statements()
        order = list(statements)
        judgments = {k: StatementJudgment.model_validate(v) for k, v in rec["judgments"].items()}
        qc = rec.get("quote_check") or {}
        reasons: dict[str, str] = {}
        for k in statements:
            j = judgments.get(k)
            if j is None or j.verdict == "unknown":
                reasons[k] = "유보"
            elif qc.get(k) is False:
                reasons[k] = "인용 불일치"
            elif c.stance_check and _stance_conflict(j):
                reasons[k] = "인용-결론 불일치"
            elif (rec.get("cite_check") or {}).get(k, {}).get("weak"):
                reasons[k] = "근거 약함"
            elif j.confidence < c.research_conf:
                reasons[k] = "낮은 확신도"
        tied = tied_options(rec.get("option_scores") or {}, ratio=c.rejudge_ratio)
        if len(tied) > 1:
            for k in statements:
                if k not in reasons and len({_required(q, n).get(k) for n in tied}) > 1:
                    reasons[k] = "근소 차"
        if c.mismatch_check and rec.get("predicted") is not None:  # ④ 고른 보기와 어긋난 고확신 진술
            req = _required(q, rec["predicted"])
            for k, j in judgments.items():
                if j.verdict != "unknown" and k in req and (j.verdict == "true") != req[k] and j.confidence >= 0.9:
                    reasons.setdefault(k, "답과 불일치")
        if c.counter_check and rec.get("predicted") is not None:
            for k in self._decisive(q, judgments, rec["predicted"]):
                reasons.setdefault(k, "반대 근거 확인")
        rank = ["유보", "인용 불일치", "인용-결론 불일치", "근거 약함", "답과 불일치", "낮은 확신도", "근소 차",
                "반대 근거 확인"]
        keys = sorted(reasons, key=lambda k: (rank.index(reasons[k]), order.index(k)))[: c.research_max_keys]
        if not keys:
            return rec
        info: dict = {"keys": keys, "reasons": {k: reasons[k] for k in keys}, "queries": {}, "new_ids": [],
                      "changed": {}, "rejected": {}, "error": None, "before": rec.get("predicted")}
        rec["research"] = info
        t = time.perf_counter()
        merge = self.graph if c.merge_case_pieces else None
        meta = (self.full_court if self.full_court is not None else None) if c.case_meta else False
        have = set(used)
        blocks: list[str] = []
        try:
            for k in keys:
                j = judgments.get(k)
                base = (j.restated if j is not None and j.restated else None) or statements[k]
                qs = []
                if j is not None and j.missing and len(j.missing.strip()) >= 4:
                    qs.append(j.missing.strip())
                if reasons[k] == "반대 근거 확인":
                    qs.append(base + " 예외 다만 반대")
                if not qs or reasons[k] in ("인용 불일치", "근소 차"):
                    qs.append(base)
                if reasons[k] in ("인용-결론 불일치", "근거 약함", "답과 불일치"):  # 리라이트에 흔들리지 않게 원문도
                    qs += [x for x in (base, statements[k]) if x not in qs]
                info["queries"][k] = qs
                finals = [self._retrieve(x, mode, cutoff)["final"] for x in qs]
                fused = finals[0] if len(finals) == 1 else rrf_fuse(
                    {f"q{i}": f for i, f in enumerate(finals)}, rrf_k=self.s.retrieval.rrf_k, top_k=self.s.retrieval.final_k)
                n = 0
                for r in fused:
                    cid = r.chunk.chunk_id
                    ids = merge.item_pieces(cid) if merge is not None else [cid]
                    if any(x in have for x in ids):
                        continue
                    have.update(ids)
                    info["new_ids"].extend(ids)
                    text = merge.item_text(cid) if merge is not None else r.chunk.text
                    blocks.append(_doc(cid, r.chunk, text, "research", meta=meta,
                                       attrs=annotate(r.chunk) if annotate else ""))
                    n += 1
                    if n >= c.research_k:
                        break
        except Exception as e:
            info["error"] = f"{type(e).__name__}: {e}"
            return rec
        info["timing_retrieval_ms"] = round((time.perf_counter() - t) * 1000, 1)
        if not blocks:  # 새 근거가 없어도 유보·인용 불일치는 같은 근거로 한 번 더 대조 (연결 근거를 놓쳤을 수 있음)
            info["no_new_evidence"] = True
            if not any(info["reasons"][k] in ("유보", "인용 불일치", "인용-결론 불일치", "답과 불일치") for k in keys):
                return rec
            blocks = ["(추가로 찾은 새 근거 없음 — <evidence> 를 다시 대조하세요)"]
        previous = "\n".join(
            f"{k}. " + (f"{judgments[k].verdict} (확신도 {judgments[k].confidence}) {judgments[k].reason[:300]}"
                        if k in judgments else "판단 없음") for k in keys)
        user = MCQ_RESEARCH_USER.format(
            evidence=evidence, new_evidence="\n\n".join(blocks), stem=q.stem,
            statements="\n".join(f"{k}. {statements[k]}" for k in keys), previous=previous,
            reasons=", ".join(sorted(set(info["reasons"].values()), key=rank.index)), keys=", ".join(keys))
        try:
            again = self._call_judgments(system, user, keys, "research", rec, 1)
        except Exception as e:
            info["error"] = f"{type(e).__name__}: {e}"
            return rec
        for k, nj in again.items():
            old = judgments.get(k)
            if nj.verdict == "unknown":
                info["rejected"][k] = "unknown"
                continue
            ok = self._quote_ok(nj) if nj.source == "evidence" else None
            if old is None or old.verdict == "unknown":
                accept = ok is not False and nj.confidence >= c.rejudge_min_conf
            else:
                accept = ok is True and nj.confidence >= old.confidence
            if accept:
                info["changed"][k] = {"from": [old.verdict, old.confidence] if old else None,
                                      "to": [nj.verdict, nj.confidence], "quote_ok": ok}
                judgments[k] = nj
                if c.quote_check:
                    rec.setdefault("quote_check", {})[k] = ok
            else:
                info["rejected"][k] = {"to": [nj.verdict, nj.confidence], "quote_ok": ok}
        if info["changed"]:
            predicted, scores, chk = self._choose(q, judgments)
            rec.update(judgments={k: j.model_dump() for k, j in judgments.items()}, option_scores=scores,
                       predicted=predicted, answer_check=chk)
            if rec["status"] in ("insufficient_evidence", "inconsistent_judgments") and predicted is not None:
                rec["status"] = "inconsistent_judgments" if chk.get("inconsistent") else "ok"
        info["after"] = rec.get("predicted")
        rec["timing_ms"]["research"] = round((time.perf_counter() - t) * 1000, 1)
        rec["timing_ms"]["total"] = round((time.perf_counter() - t0) * 1000, 1)
        return rec

    def _call_judgments(self, system: str, user: str, keys: list[str], step: str, rec: dict,
                        n: int = 1) -> dict[str, StatementJudgment]:
        """판단 LLM 호출. n>1 이면 n번 불러 진술별 다수결 (4-1): 같은 표 수면 그 진술은 바꾸지 않음."""
        runs = []
        for _ in range(max(1, n)):
            raw, calls = call_llm(self.s.models.llm_provider, self.s.models.llm_model,
                                  [("system", system), ("human", user)], self.s.mcq.max_tokens)
            rec.setdefault("llm_calls", []).extend({"step": step, **x} for x in calls)
            runs.append(_parse_judgments(raw, keys))
        if len(runs) == 1:
            return runs[0]
        out: dict[str, StatementJudgment] = {}
        for k in keys:
            js = [r[k] for r in runs if k in r and r[k].verdict != "unknown"]
            if not js:
                continue
            cnt = Counter(j.verdict for j in js).most_common()
            if len(cnt) > 1 and cnt[0][1] == cnt[1][1]:
                continue
            v, m = cnt[0]
            if self.s.mcq.vote_strict and m * 2 <= len(runs):  # ⑤ 유보 표도 세어 전체 과반이 아니면 바꾸지 않음
                continue
            maj = [j for j in js if j.verdict == v]
            conf = sum(j.confidence for j in maj) / len(maj) * m / len(runs)
            out[k] = max(maj, key=lambda j: j.confidence).model_copy(update={"confidence": round(conf, 3)})
        rec.setdefault("votes", {})[step] = {k: [r[k].verdict if k in r else None for r in runs] for k in keys}
        return out

    @property
    def corpus_titles(self) -> set[str]:
        if getattr(self, "_titles", None) is None:
            self._titles = {ch.title for ch in self.retriever.vector.chunks_by_id.values()
                            if (ch.metadata or {}).get("doc_type") == "statute"}
        return self._titles

    @property
    def calibrator(self) -> Calibrator | None:
        if not hasattr(self, "_cal"):
            self._cal = Calibrator.load(self.s.mcq.calibration and self.s.resolve(Path(self.s.mcq.calibration)))
        return self._cal

    def _check_quotes(self, q: ExamQuestion, rec: dict) -> dict:
        """판단의 인용 문장이 인용한 청크에 실제로 있는지 대조. 없으면 확신도 × quote_penalty (v5)."""
        c = self.s.mcq
        judgments = {k: StatementJudgment.model_validate(v) for k, v in rec["judgments"].items()}
        check: dict = {}
        for k, j in judgments.items():
            if j.verdict == "unknown" or j.source == "knowledge":
                continue
            ok = self._quote_ok(j)
            check[k] = ok
            if ok is False and c.quote_penalty < 1.0:
                judgments[k] = j.model_copy(update={"confidence": round(j.confidence * c.quote_penalty, 3)})
        rec["quote_check"] = check
        if any(v is False for v in check.values()) and c.quote_penalty < 1.0:
            predicted, scores, chk = self._choose(q, judgments)
            rec.update(judgments={k: j.model_dump() for k, j in judgments.items()}, option_scores=scores,
                       predicted=predicted, answer_check=chk)
        return rec

    def _tiebreak(self, q: ExamQuestion, rec: dict, t0: float, system: str, evidence: str, used: list[str]) -> dict:
        """최고점 보기가 둘 이상이면(동점) 그 보기들 사이에서 요구가 갈리는 진술만 근거와 다시 판단한다 (LLM 1회)."""
        c = self.s.mcq
        tied = tied_options(rec.get("option_scores") or {}, ratio=c.rejudge_ratio)
        count_mode = False
        if len(tied) < 2 and q.form == "count" and c.count_tie:  # 5-1 개수형: 기대 개수가 두 보기 사이
            ranked = sorted((rec.get("option_scores") or {}).items(), key=lambda kv: -kv[1])
            if len(ranked) >= 2 and ranked[0][1] - ranked[1][1] <= 0.5 + 1e-9:
                tied, count_mode = sorted(int(n) for n, _ in ranked[:2]), True
        if len(tied) < 2:
            return rec
        if count_mode:
            js0 = {k: StatementJudgment.model_validate(v) for k, v in rec["judgments"].items()}
            keys = [k for k in q.statements() if (j := js0.get(k)) is None or j.verdict == "unknown"
                    or j.confidence < c.research_conf]
        else:
            keys = [k for k in q.statements() if len({_required(q, n).get(k) for n in tied}) > 1]
        info: dict = {"tied": tied, "keys": keys, "before": rec.get("predicted"), "error": None}
        if count_mode:
            info["count_tie"] = True
        rec["tiebreak"] = info
        if not keys:
            rec["status"] = "tie"
            return rec
        statements = q.statements()
        listing = "\n".join(f"{k}. {statements[k]}" for k in keys)
        same = c.rejudge_ratio >= 1.0
        if count_mode:
            note = "개수형: 옳은 진술 개수가 보기 " + " 와 ".join(CIRCLED_NUM[n - 1] for n in tied) + " 사이에 걸림"
        else:
            note = "보기 " + ", ".join(CIRCLED_NUM[n - 1] for n in tied) + (" 가 같은 점수" if same else " 의 점수 차이가 작음")
        t = time.perf_counter()
        try:
            again = self._call_judgments(system, MCQ_TIEBREAK_USER.format(
                evidence=evidence, stem=q.stem, statements=listing, note=note, keys=", ".join(keys)),
                keys, "tiebreak", rec, c.vote_n)
        except Exception as e:  # 실패하면 기존 판단 유지
            info["error"] = f"{type(e).__name__}: {e}"
            rec["status"] = "tie"
            return rec
        rec["timing_ms"]["tiebreak"] = round((time.perf_counter() - t) * 1000, 1)
        judgments = {k: StatementJudgment.model_validate(v) for k, v in rec["judgments"].items()}
        info["changed"] = {}
        for k, j in again.items():
            if j.verdict == "unknown":
                continue
            old = judgments.get(k)
            if (old is None or old.verdict == "unknown") and j.confidence < c.rejudge_min_conf:  # ⑥ 약한 표로 유보 대체 금지
                info.setdefault("rejected", {})[k] = [j.verdict, j.confidence]
                continue
            if old is None or (old.verdict, old.confidence) != (j.verdict, j.confidence):
                info["changed"][k] = {"from": [old.verdict, old.confidence] if old else None,
                                      "to": [j.verdict, j.confidence]}
            judgments[k] = j
        predicted, scores, chk = self._choose(q, judgments)
        rec.update(judgments={k: j.model_dump() for k, j in judgments.items()}, option_scores=scores,
                   predicted=predicted)
        rec["answer_check"] = chk
        info["after"] = predicted
        if q.form == "count":
            top2 = sorted(scores.values(), reverse=True)[:2]
            still = len(top2) == 2 and abs(top2[0] - top2[1]) <= 1e-9
        else:
            still = len(tied_options(scores)) > 1  # 재판단 후에도 완전 동점이면 tie
        rec["status"] = "tie" if still else ("inconsistent_judgments" if chk.get("inconsistent") else
                                             ("ok" if rec["status"] in ("ok", "tie") else rec["status"]))
        rec["timing_ms"]["total"] = round((time.perf_counter() - t0) * 1000, 1)
        return rec

    def _choose(self, q: ExamQuestion, judgments: dict[str, StatementJudgment]):
        c = self.s.mcq
        cal = self.calibrator if c.calibration else None
        if cal is not None:  # 보정 확률로 점수 계산 (v5): 0점·동점이 잘 생기지 않음
            best, scores = choose_answer(q, judgments, support=cal.support())
            if best is None:
                return best, scores, {"inconsistent": False, "flipped": []}
            req = _required(q, best)
            flipped = [k for k, want in req.items() if (j := judgments.get(k)) is not None
                       and j.verdict != "unknown" and (j.verdict == "true") != want]
            return best, scores, {"inconsistent": not exact_match_exists(q, judgments), "flipped": flipped,
                                  "calibrated": True}
        if c.answer_fallback:
            return choose_answer_robust(q, judgments, c.answer_fallback_cap)
        best, scores = choose_answer(q, judgments)
        return best, scores, {"inconsistent": False, "flipped": []}

    def _fuse(self, q: ExamQuestion, rec: dict, t0: float) -> dict:
        """개선안 C: 근거로 유보(unknown)한 진술만 같은 모델의 closed-book 판단으로 채움 (확신도 × fusion_weight)."""
        c = self.s.mcq
        statements = q.statements()
        unknown = [k for k in statements if rec["judgments"].get(k, {}).get("verdict", "unknown") == "unknown"]
        rec["fusion"] = {"unknown_keys": unknown, "filled": {}, "error": None}
        if not unknown:
            return rec
        t = time.perf_counter()
        try:
            listing = "\n".join(f"{k}. {statements[k]}" for k in unknown)
            raw, calls = call_llm(self.s.models.llm_provider, self.s.models.llm_model,
                                  [("system", MCQ_CLOSED_SYSTEM),
                                   ("human", MCQ_FUSION_USER.format(stem=q.stem, statements=listing,
                                                                    keys=", ".join(unknown)))], c.max_tokens)
            rec.setdefault("llm_calls", []).extend({"step": "fusion", **x} for x in calls)
            kb = _parse_judgments(raw, unknown)
        except Exception as e:  # 실패하면 RAG 판단 그대로
            rec["fusion"]["error"] = f"{type(e).__name__}: {e}"
            return rec
        rec["timing_ms"]["fusion"] = round((time.perf_counter() - t) * 1000, 1)
        judgments = {k: StatementJudgment.model_validate(v) for k, v in rec["judgments"].items()}
        for k, j in kb.items():
            if j.verdict == "unknown":
                continue
            if j.confidence < c.fusion_min_conf:  # 확신이 낮은 지식 판단은 채우지 않고 유보로 둠
                rec["fusion"].setdefault("skipped_low_conf", {})[k] = {"verdict": j.verdict, "raw_confidence": j.confidence}
                continue
            filled = j.model_copy(update={"confidence": round(j.confidence * c.fusion_weight, 3),
                                          "reason": "[지식 판단·근거 없음] " + j.reason,
                                          "cited_chunk_ids": [], "source": "knowledge"})
            judgments[k] = filled
            rec["fusion"]["filled"][k] = {"verdict": j.verdict, "raw_confidence": j.confidence}
        predicted, scores, chk = self._choose(q, judgments)
        rec["rag_predicted"] = rec.get("predicted")
        rec["answer_check"] = chk
        rec.update(judgments={k: j.model_dump() for k, j in judgments.items()}, option_scores=scores,
                   predicted=predicted)
        if rec["status"] in ("insufficient_evidence", "inconsistent_judgments") and predicted is not None:
            rec["status"] = "inconsistent_judgments" if chk["inconsistent"] else "ok"
        rec["knowledge_used"] = bool(rec["fusion"]["filled"])
        rec["timing_ms"]["total"] = round((time.perf_counter() - t0) * 1000, 1)
        return rec

    def _judge(self, q: ExamQuestion, rec: dict, t0: float, system: str, user: str, used: list[str]) -> dict:
        statements = q.statements()
        t = time.perf_counter()
        try:
            raw, calls = call_llm(self.s.models.llm_provider, self.s.models.llm_model,
                                  [("system", system), ("human", user)], self.s.mcq.max_tokens)
            rec.setdefault("llm_calls", []).extend({"step": "judge", **c} for c in calls)
            rec["raw_output"] = raw
            judgments = _parse_judgments(raw, list(statements))
        except Exception as e:
            rec.update(status="generation_error", error=f"{type(e).__name__}: {e}", predicted=None)
            rec["timing_ms"]["total"] = round((time.perf_counter() - t0) * 1000, 1)
            return rec
        rec["timing_ms"]["generation"] = round((time.perf_counter() - t) * 1000, 1)

        invalid = sorted({cid for j in judgments.values() for cid in j.cited_chunk_ids if cid not in used})
        predicted, scores, chk = self._choose(q, judgments)
        rec["answer_check"] = chk
        rec.update(
            judgments={k: j.model_dump() for k, j in judgments.items()},
            missing_judgments=[k for k in statements if k not in judgments],
            invalid_citations=invalid,
            option_scores=scores,
            predicted=predicted,
        )
        if predicted is None:
            rec["status"] = "insufficient_evidence"
        elif invalid:
            rec["status"] = "invalid_citation"
        elif chk["inconsistent"]:
            rec["status"] = "inconsistent_judgments"  # 판단 조합이 어느 보기와도 맞지 않아 예비 규칙으로 고름
        elif len(tied_options(scores)) > 1:  # 동점 (재판단이 꺼진 구성에서도 드러나게; 예측 번호는 그대로)
            rec["status"] = "tie"
            rec["tied"] = tied_options(scores)
        rec["timing_ms"]["total"] = round((time.perf_counter() - t0) * 1000, 1)
        return rec
