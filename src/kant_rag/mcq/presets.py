"""개선안 v3 단계별 비교(ablation) 프리셋. 각 단계는 이전 단계에 하나씩 더한다.

  v2   : 현재 기준 (근거 4개, 리라이트 없음, 프롬프트 v1)
  a1   : + 진술당 근거 5개
  a2   : + 쿼리 리라이트(쟁점·예외 질의 2개)
  a34  : + 같은 판결 다른 항목(A3) + 준용 조문(A4)
  b    : + 판단 프롬프트 v2
  c    : + closed-book 판단 결합(유보 진술만, 확신도×0.5)  = v3 전체
  d    : b + 번호 계산 예비 규칙 + 당사자 지위 리라이트(질의 3개) + 진술 원문 질의 + 판례 선고일·전원합의체 표시
         + 판단 프롬프트 v4(진술 풀어 쓰기·조문 단서 범위) + 동점 재판단
  dc   : d + 판단 결합(지식 원 확신도 0.8 이상만)
  v4   : = d (별칭)
  v5   : v4 + 발문 기준 시점·색인 밖 법령 경고·진술 간 참조·발문 전체 리라이트·인용 대조·근소 차 재판단
  v5c  : v5 + 판단 결합(지식 원 확신도 0.8 이상만)
  v6   : v5 + 연결 지도(판례 변경·조문→판례·판례→판례)·역방향 준용·판결요지 조각 합치기·조문 보충(final_k 8)
         + 다시 찾는 검색(유보·저확신·인용 불일치·근소 차 진술 2차 검색 후 재판단)·개수형 동점 재판단
         + 인용 대조 완화·리라이트 키 정규화·판단 프롬프트 v6(missing)
         + 조문 위치(편·장) 표시·회사 종류가 다른 장이면 준용 조문 연결(M1)·조문 제목 일치 조문 연결(M2)   (docs/analysis/improvement-plan-v6.md A-1·A-2)
  v6r  : v6 + 반대 근거 확인·근소 차 다수결(3회)·근거 없는 판단 감점·전원합의체/최근 판례 가산   (A-3)
  v6r2 : v6r + 근거 적합성 검사·원문 질의 결과 보장·인용-결론 일치(판단 v7 stance)·답과 어긋난 진술 재검토
         + 다수결 엄격(유보 표 포함 과반)·재판단 확신도 하한 0.6   (docs/analysis/v6r2-design.md, 2022 검증 세트 오답)
  v6r2-lite : v6r2 + 판단 입력 축소 (같은 판결 항목 3·준용 4·연결 1·28000→20000자)
"""

from __future__ import annotations

import copy
from typing import Any

import yaml

PRESETS: dict[str, dict[str, Any]] = {"v2": {}}
PRESETS["a1"] = {**PRESETS["v2"], "mcq.per_statement_k": 5}
PRESETS["a2"] = {**PRESETS["a1"], "optimization.rewrite.enabled": True, "mcq.rewrite_queries": 2}
PRESETS["a34"] = {**PRESETS["a2"], "mcq.sibling_items": True, "mcq.expand_references": True,
                  "mcq.max_context_chars": 24000}
PRESETS["b"] = {**PRESETS["a34"], "mcq.prompt_version": "v2"}
PRESETS["c"] = {**PRESETS["b"], "mcq.fusion": "fill_unknown"}
PRESETS["v3"] = PRESETS["c"]
# 개선안 v4 (bar13 오답 분석): b 기반 + 번호 계산 예비 규칙 + 당사자 지위 리라이트 + 판례 선고일·전원합의체 표시 + 판단 프롬프트 v3
PRESETS["d"] = {**PRESETS["b"], "mcq.answer_fallback": True, "mcq.rewrite_version": "v3", "mcq.rewrite_queries": 3,
                "mcq.rewrite_stem_chars": 800, "mcq.case_meta": True, "mcq.prompt_version": "v4",
                # 적대적 변형본 분석 (docs/analysis/report-2026-adv-v3.md): 진술 풀어 쓰기, 원문 질의, 동점 재판단
                "mcq.original_query": True, "mcq.tie_rejudge": True, "mcq.statute_parts": True}
PRESETS["dc"] = {**PRESETS["d"], "mcq.fusion": "fill_unknown", "mcq.fusion_min_conf": 0.8}  # d + 지식 결합(원 확신도 0.8 이상만)
PRESETS["v4"] = PRESETS["d"]  # 별칭: --preset v4 = d
# v5 (레드팀 공략안 + 구조 분석): v4 + 발문 기준 시점, 색인 밖 법령 경고, 진술 간 참조 질의, 리라이트 v4(발문 전체),
# 판단 v5(인용 문장·가정 사실·논거 분리), 인용 대조(실패 시 확신도 ×0.85), 점수 차이가 작은 보기 재판단(2등 ≥ 1등×0.5).
# 확신도 보정(mcq.calibration)은 기존 기록 재계산에서 오히려 낮아져(v2 58→57, bar13 closed-book 53→49) 기본에서 뺐다.
# 표본이 쌓이면 --set mcq.calibration=configs/calibration.json 으로 비교
PRESETS["v5"] = {**PRESETS["d"], "mcq.asof_from_stem": True, "mcq.out_of_corpus_warn": True,
                 "mcq.cross_ref_queries": True, "mcq.rewrite_version": "v4", "mcq.rewrite_stem_chars": 0,
                 "mcq.prompt_version": "v5", "mcq.quote_check": True, "mcq.quote_penalty": 0.85,
                 "mcq.rejudge_ratio": 0.5}
PRESETS["v5c"] = {**PRESETS["v5"], "mcq.fusion": "fill_unknown", "mcq.fusion_min_conf": 0.8}
# v6 (개선안 v6 A-1·A-2): 추가 데이터 없이 원자료의 참조판례·참조조문을 쓰고, 모르거나 확신이 낮으면 한 번 더 찾는다
PRESETS["v6"] = {**PRESETS["v5"], "mcq.prompt_version": "v6", "mcq.rewrite_key_normalize": True,
                 "mcq.quote_match": "relaxed", "mcq.links": True, "mcq.reverse_usage": True,
                 "mcq.merge_case_pieces": True, "mcq.type_balance": True, "retrieval.final_k": 8,
                 "mcq.research": True, "mcq.count_tie": True, "mcq.max_context_chars": 28000,
                 "mcq.chapter_check": True, "mcq.title_search": True}
# v6r (A-3): 반대 근거·다수결·근거 없음 감점·판례 가산 — 비용이 늘어 따로 비교
PRESETS["v6r"] = {**PRESETS["v6"], "mcq.counter_check": True, "mcq.vote_n": 3, "mcq.no_evidence_penalty": 0.8,
                  "mcq.recency_boost": 0.1, "mcq.research_max_keys": 5}


def parse_sets(items: list[str] | None) -> dict[str, Any]:
    """['mcq.per_statement_k=5', 'mcq.fusion=fill_unknown'] → dict (값은 YAML 로 해석)."""
    out: dict[str, Any] = {}
    for it in items or []:
        key, _, val = it.partition("=")
        if not key or not _:
            raise SystemExit(f"--set 형식은 key=value 입니다: {it}")
        out[key.strip()] = yaml.safe_load(val)
    return out


def apply_overrides(settings, overrides: dict[str, Any]):
    """점 경로(mcq.per_statement_k)로 설정을 덮어쓴 새 Settings. 없는 경로는 오류."""
    data = copy.deepcopy(settings.model_dump())
    for path, val in overrides.items():
        node = data
        parts = path.split(".")
        for p in parts[:-1]:
            if p not in node or not isinstance(node[p], dict):
                raise SystemExit(f"설정 경로가 없습니다: {path}")
            node = node[p]
        if parts[-1] not in node:
            raise SystemExit(f"설정 경로가 없습니다: {path}")
        node[parts[-1]] = val
    return type(settings).model_validate(data)

# v6r2 (2022 검증 세트 오답: 문 11 ㄹ 검색 변동·근거 없이 단정, 문 24 ㄷ 근거 인용하고 반대 판단, 다수결이 유보를 약한 표로 대체)
PRESETS["v6r2"] = {**PRESETS["v6r"], "mcq.cite_relevance": True, "mcq.cite_min_score": 0.3, "mcq.original_keep": 2,
                   "mcq.stance_check": True, "mcq.prompt_version": "v7", "mcq.mismatch_check": True,
                   "mcq.vote_strict": True, "mcq.rejudge_min_conf": 0.6, "mcq.research_max_keys": 6}
PRESETS["v6r2-lite"] = {**PRESETS["v6r2"], "mcq.max_siblings": 3, "mcq.max_expansions": 4, "mcq.link_k": 1,
                        "mcq.max_context_chars": 20000}
