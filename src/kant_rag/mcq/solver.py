"""선택형 풀이: 진술별 검색 → LLM 진술 정오 판단 → 규칙으로 정답 번호 결정.

LLM 에게 번호를 직접 고르게 하지 않고, 진술별 판단(verdict)과 발문의 극성/형식(옳은 것/옳지 않은 것,
단일/조합/개수)으로 정답을 계산합니다. 덕분에 '검색 누락 → 진술 판단 오류 → 정답 오류' 를 단계별로 분석할 수 있습니다.
"""

from __future__ import annotations

import re
import time
from pathlib import Path

from kant_rag.config import Settings
from kant_rag.generation.llmcall import call_llm, extract_json
from kant_rag.mcq.parse import parse_combo, parse_ox
from kant_rag.mcq.context import ChunkGraph
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
    MCQ_REWRITE_SYSTEM_V4,
    MCQ_TIEBREAK_USER,
    MCQ_USER,
)
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
        data = extract_json(raw)
    except Exception as e:
        data = {}
        info["error"] = f"{type(e).__name__}: {e}"
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
    return queries, info


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


def _doc(cid: str, chunk, text: str, kind: str | None = None, meta: set[str] | None | bool = False) -> str:
    k = f' kind="{kind}"' if kind else ""
    extra = _case_attrs(chunk, meta if isinstance(meta, set) else None) if meta is not False else ""
    return f'<doc id="{cid}" title="{chunk.title}" loc="{chunk.location()}"{k}{extra}>\n{text}\n</doc>'


def full_court_cases(chunks_by_id: dict) -> set[str]:
    """판결요지에 다수의견·반대의견 등이 있는 판례 = 전원합의체 (사건번호 집합)."""
    out: set[str] = set()
    for c in chunks_by_id.values():
        md = c.metadata or {}
        if md.get("doc_type") == "case" and any(m in c.text for m in FULL_COURT_MARKS):
            out.add(md.get("case_no"))
    return out


def build_context(per_statement: dict[str, list[RetrievedChunk]], c, graph: ChunkGraph | None,
                  full_court: set[str] | None = None) -> tuple[str, list[str], dict]:
    """진술당 상위 k 근거(중복 제거) + 개선안 A3(같은 판결 다른 항목)·A4(준용 조문) 확장."""
    seen: dict[str, RetrievedChunk] = {}
    for results in per_statement.values():  # 진술 순서대로, 진술당 상위 k 개
        for r in results[: c.per_statement_k]:
            seen.setdefault(r.chunk.chunk_id, r)
    parts, used, total = [], [], 0
    for cid, r in seen.items():
        meta = (full_court if full_court is not None else None) if c.case_meta else False
        block = _doc(cid, r.chunk, r.chunk.text, meta=meta)
        if total + len(block) > c.max_context_chars and used:
            break
        parts.append(block)
        used.append(cid)
        total += len(block)
    info = {"siblings": [], "references": []}
    if graph is not None:
        extra: list[tuple[str, str, str]] = []  # (id, text, kind)
        if c.expand_references:
            extra += [(x, graph.by_id[x].text, "reference") for x in graph.expand_references(used, c.max_expansions)]
        if getattr(c, "statute_parts", False):
            extra += [(x, graph.by_id[x].text, "part") for x in graph.statute_parts(used, c.max_statute_parts)]
        if c.sibling_items:
            extra += [(x, t, "sibling") for x, t in graph.case_siblings(used, max_total=c.max_siblings)]
        for cid, text, kind in extra:
            block = _doc(cid, graph.by_id[cid], text, kind,
                         meta=(full_court if full_court is not None else None) if c.case_meta else False)
            if total + len(block) > c.max_context_chars:
                continue
            parts.append(block)
            used.append(cid)
            total += len(block)
            info.setdefault({"reference": "references", "sibling": "siblings", "part": "statute_parts"}[kind], []).append(cid)
    return "\n\n".join(parts), used, info


class MCQSolver:
    def __init__(self, settings: Settings, retriever: Retriever | None = None):
        self.s = settings
        self._retriever = retriever

    @property
    def retriever(self) -> Retriever:  # closed-book 만 돌릴 때는 색인을 읽지 않음
        if self._retriever is None:
            self._retriever = Retriever(self.s)
        return self._retriever

    @property
    def graph(self) -> ChunkGraph | None:  # A3·A4 를 켰을 때만 생성
        c = self.s.mcq
        if not (c.sibling_items or c.expand_references or c.statute_parts):
            return None
        if getattr(self, "_graph", None) is None:
            self._graph = ChunkGraph(self.retriever.vector.chunks_by_id)
        return self._graph

    @property
    def full_court(self) -> set[str] | None:  # case_meta 를 켰을 때만 계산
        if not self.s.mcq.case_meta:
            return None
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
        if cutoff:
            rec["asof"] = cutoff
        rec["search_queries"] = queries

        t = time.perf_counter()
        per_statement: dict[str, list[RetrievedChunk]] = {}
        rec["retrieval"] = {}
        try:
            for key in statements:
                finals = [self.retriever.retrieve(qq, mode, cutoff)["final"] if cutoff else
                          self.retriever.retrieve(qq, mode)["final"] for qq in queries[key]]
                if len(finals) == 1:
                    per_statement[key] = finals[0]
                else:  # 쟁점·예외 질의 결과를 순위로 결합 (RRF)
                    per_statement[key] = rrf_fuse({f"q{i}": f for i, f in enumerate(finals)},
                                                  rrf_k=self.s.retrieval.rrf_k, top_k=self.s.retrieval.final_k)
                rec["retrieval"][key] = [
                    {"rank": r.rank, "chunk_id": r.chunk.chunk_id, "score": r.score, **r.trace}
                    for r in per_statement[key]
                ]
        except Exception as e:
            rec.update(status="retrieval_error", error=f"{type(e).__name__}: {e}", predicted=None)
            rec["timing_ms"]["total"] = round((time.perf_counter() - t0) * 1000, 1)
            return rec
        rec["timing_ms"]["retrieval"] = round((time.perf_counter() - t) * 1000, 1)

        evidence, used, exp = build_context(per_statement, c, self.graph, self.full_court)
        rec["context_chunk_ids"] = used
        rec["context_expansions"] = exp
        rec["prompt_version"] = c.prompt_version
        system = {"v2": MCQ_SYSTEM_V2, "v3": MCQ_SYSTEM_V3, "v4": MCQ_SYSTEM_V4,
                  "v5": MCQ_SYSTEM_V5}.get(c.prompt_version, MCQ_SYSTEM)
        user = MCQ_USER.format(evidence=evidence, stem=q.stem, statements=listing, keys=", ".join(statements))
        if c.out_of_corpus_warn:  # 색인에 없는 법령이 쟁점이면 판단 입력에 경고 (v5)
            miss = out_of_corpus(q.stem + "\n" + listing, self.corpus_titles)
            if miss:
                rec["out_of_corpus"] = miss
                user = f"[색인 밖 법령] 다음 법령은 근거 자료에 없습니다: {', '.join(miss)}\n\n" + user
        rec = self._judge(q, rec, t0, system, user, used)
        if c.quote_check and rec.get("judgments") is not None:
            rec = self._check_quotes(q, rec)
        if c.fusion == "fill_unknown" and rec.get("judgments") is not None:
            rec = self._fuse(q, rec, t0)
        if c.tie_rejudge and rec.get("judgments") is not None:
            rec = self._tiebreak(q, rec, t0, system, evidence, used)
        return rec

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
        by_id = self.retriever.vector.chunks_by_id
        judgments = {k: StatementJudgment.model_validate(v) for k, v in rec["judgments"].items()}
        check: dict = {}
        for k, j in judgments.items():
            if j.verdict == "unknown" or j.source == "knowledge":
                continue
            texts = [by_id[x].text for x in j.cited_chunk_ids if x in by_id]
            ok = quote_supported(j.quote, texts)
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
        tied = tied_options(rec.get("option_scores") or {}, ratio=self.s.mcq.rejudge_ratio)
        if len(tied) < 2:
            return rec
        keys = [k for k in q.statements() if len({_required(q, n).get(k) for n in tied}) > 1]
        info: dict = {"tied": tied, "keys": keys, "before": rec.get("predicted"), "error": None}
        rec["tiebreak"] = info
        if not keys:
            rec["status"] = "tie"
            return rec
        statements = q.statements()
        listing = "\n".join(f"{k}. {statements[k]}" for k in keys)
        same = self.s.mcq.rejudge_ratio >= 1.0
        note = "보기 " + ", ".join(CIRCLED_NUM[n - 1] for n in tied) + (" 가 같은 점수" if same else " 의 점수 차이가 작음")
        t = time.perf_counter()
        try:
            raw, calls = call_llm(self.s.models.llm_provider, self.s.models.llm_model,
                                  [("system", system), ("human", MCQ_TIEBREAK_USER.format(
                                      evidence=evidence, stem=q.stem, statements=listing, note=note,
                                      keys=", ".join(keys)))], self.s.mcq.max_tokens)
            rec.setdefault("llm_calls", []).extend({"step": "tiebreak", **x} for x in calls)
            again = _parse_judgments(raw, keys)
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
            if old is None or (old.verdict, old.confidence) != (j.verdict, j.confidence):
                info["changed"][k] = {"from": [old.verdict, old.confidence] if old else None,
                                      "to": [j.verdict, j.confidence]}
            judgments[k] = j
        predicted, scores, chk = self._choose(q, judgments)
        rec.update(judgments={k: j.model_dump() for k, j in judgments.items()}, option_scores=scores,
                   predicted=predicted)
        rec["answer_check"] = chk
        info["after"] = predicted
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
        rec["timing_ms"]["total"] = round((time.perf_counter() - t0) * 1000, 1)
        return rec
