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
                "mcq.original_query": True, "mcq.tie_rejudge": True}
PRESETS["dc"] = {**PRESETS["d"], "mcq.fusion": "fill_unknown", "mcq.fusion_min_conf": 0.8}  # d + 지식 결합(원 확신도 0.8 이상만)
PRESETS["v4"] = PRESETS["d"]  # 별칭: --preset v4 = d


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
