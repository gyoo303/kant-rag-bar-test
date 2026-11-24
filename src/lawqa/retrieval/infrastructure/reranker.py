"""검색 구성 C: 구성 B 결과 → CrossEncoder 재정렬 → 상위 `k_opt` (ADR-010, S-04·S-05·S-10).

- 재정렬은 `CrossEncoderReranker`(langchain_classic) + `HuggingFaceCrossEncoder`
  (`BAAI/bge-reranker-v2-m3`, 장치는 설정 `reranker_device`). LLM 재정렬이 아니다.
- `CrossEncoderReranker`는 점수를 문서에 붙이지 않는다(S-04 확인). 그래서 모델을
  `RecordingCrossEncoder`로 감싸 재정렬이 계산한 점수를 그대로 기록한다(GPU 계산은 한 번).
- 기록: 재정렬 전 순위 = `fused_rank`(구성 B 순서), 재정렬 후 = `final_rank`, 점수 = `rerank_score`
  (AC-08-1). 출력 순서 = 재정렬 점수 내림차순(동점은 B 순서, AC-08-2).
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import replace

from langchain_classic.retrievers.document_compressors import CrossEncoderReranker
from langchain_community.cross_encoders import BaseCrossEncoder
from langchain_core.documents import Document

from lawqa.retrieval.domain.errors import RerankerFailedError
from lawqa.retrieval.domain.models import Candidate, RetrievalConfig
from lawqa.retrieval.domain.ports import OptionRetriever

log = logging.getLogger(__name__)

POSITION_KEY = "_fused_position"


class RecordingCrossEncoder(BaseCrossEncoder):
    """다른 CrossEncoder를 감싸 마지막으로 계산한 점수를 남긴다."""

    def __init__(self, inner: BaseCrossEncoder) -> None:
        self.inner = inner
        self.last_scores: list[float] = []

    def score(self, text_pairs: list[tuple[str, str]]) -> list[float]:
        self.last_scores = [float(s) for s in self.inner.score(text_pairs)]
        return self.last_scores


def resolve_device(requested: str) -> str:
    """`cuda`를 요청했는데 GPU를 못 쓰면 `cpu`로 바꾸고 경고를 남긴다(ADR-010)."""
    if requested != "cuda":
        return requested
    import torch

    if torch.cuda.is_available():
        return "cuda"
    log.warning("reranker_device=cuda 이지만 GPU를 쓸 수 없어 cpu로 재정렬합니다.")
    return "cpu"


def huggingface_cross_encoder(model_name: str, device: str) -> BaseCrossEncoder:
    """운영 재정렬 모델(첫 실행 때 약 2.3GB를 Hugging Face 캐시에 내려받음, S-10)."""
    from langchain_community.cross_encoders import HuggingFaceCrossEncoder

    return HuggingFaceCrossEncoder(model_name=model_name, model_kwargs={"device": device})


class RerankOptionRetriever:
    """구성 C: 구성 B 검색기의 결과(상위 `n_fuse`)를 재정렬해 상위 `k_opt`를 돌려준다."""

    def __init__(
        self, hybrid: OptionRetriever, encoder: BaseCrossEncoder, config: RetrievalConfig
    ) -> None:
        self._hybrid = hybrid
        self._encoder = RecordingCrossEncoder(encoder)
        self.compressor = CrossEncoderReranker(model=self._encoder, top_n=config.k_opt)

    def retrieve(self, query: str) -> list[Candidate]:
        fused = self._hybrid.retrieve(query)  # RetrievalFailedError는 그대로 올라간다
        if not fused:
            return []
        docs = [
            Document(page_content=c.text, metadata={POSITION_KEY: i}) for i, c in enumerate(fused)
        ]
        try:
            kept: Sequence[Document] = self.compressor.compress_documents(docs, query)
        except Exception as exc:  # 모델·GPU 오류 → 도메인 예외(ADR-004)
            raise RerankerFailedError(f"재정렬 실패: {type(exc).__name__}: {exc}") from exc
        scores = self._encoder.last_scores
        return [
            replace(
                fused[doc.metadata[POSITION_KEY]],
                rerank_score=scores[doc.metadata[POSITION_KEY]],
                final_rank=rank,
            )
            for rank, doc in enumerate(kept, start=1)
        ]
