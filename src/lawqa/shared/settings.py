"""설정 읽기 (ADR-003, 04-interfaces-api §6, CONV-10).

- 실험 설정: `config/base.toml` + 구성 파일(`A`, `B`, `C`, `C+R`).
  구성 파일은 `[run]`만 덮어쓴다(INV-08).
- 비밀값: `.env`와 환경변수. 이 모듈만 `os.environ`을 읽는다.
- `config_sha`: 사용한 설정 파일 내용의 해시. 실행 기록에 버전으로 남는다(INV-11).
"""

from __future__ import annotations

import os
import tomllib
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from dotenv import dotenv_values

from lawqa.shared.versioning import sha256_of_files

BASE_CONFIG = "base"
RUN_CONFIGS = ("A", "B", "C", "C+R")
RETRIEVAL_MODES = ("A", "B", "C")
RERANKER_DEVICES = ("cuda", "cpu")
SECRET_KEYS = ("OPENAI_API_KEY", "DATABASE_URL", "DATABASE_URL_TEST")


class SettingsError(ValueError):
    """설정 파일·환경변수가 없거나 값이 규칙에 맞지 않음."""


@dataclass(frozen=True, slots=True)
class ModelSettings:
    generation: str
    embedding: str
    embedding_dim: int
    reranker: str
    reranker_device: str


@dataclass(frozen=True, slots=True)
class ChunkingSettings:
    max_chars: int
    overlap_chars: int


@dataclass(frozen=True, slots=True)
class RetrievalSettings:
    n_vec: int
    n_bm25: int
    n_fuse: int
    k_opt: int
    rrf_c: int
    weights: tuple[float, float]
    question_list_max: int


@dataclass(frozen=True, slots=True)
class TimeoutSettings:
    generation_s: float
    rewrite_s: float
    judge_s: float


@dataclass(frozen=True, slots=True)
class PathSettings:
    raw_dir: Path
    eval_dir: Path
    results_dir: Path


@dataclass(frozen=True, slots=True)
class RunSettings:
    mode: str
    use_rewrite: bool


@dataclass(frozen=True, slots=True)
class Secrets:
    """비밀값. `repr`에 값이 나오지 않는다(로그·기록 노출 방지)."""

    openai_api_key: str | None = field(default=None, repr=False)
    database_url: str | None = field(default=None, repr=False)
    database_url_test: str | None = field(default=None, repr=False)

    def require(self, name: str) -> str:
        """필요한 비밀값을 돌려준다. 없으면 이름만 담은 `SettingsError`."""
        value = getattr(self, name)
        if not value:
            raise SettingsError(f"환경변수 {name.upper()}가 비어 있습니다. .env를 확인하세요.")
        return value


@dataclass(frozen=True, slots=True)
class Settings:
    config_name: str
    config_sha: str
    models: ModelSettings
    chunking: ChunkingSettings
    retrieval: RetrievalSettings
    timeouts: TimeoutSettings
    paths: PathSettings
    run: RunSettings
    secrets: Secrets


def load_settings(
    config_name: str = BASE_CONFIG,
    *,
    config_dir: Path = Path("config"),
    env_file: Path = Path(".env"),
    environ: Mapping[str, str] | None = None,
) -> Settings:
    """`config_dir/base.toml`과 구성 파일, `.env`·환경변수를 읽어 불변 설정 객체를 만든다.

    `environ`을 넘기면 실제 환경변수 대신 그 값을 쓴다(시험용).
    """
    base_path = config_dir / f"{BASE_CONFIG}.toml"
    files = [base_path]
    data = _read_toml(base_path)

    if config_name != BASE_CONFIG:
        if config_name not in RUN_CONFIGS:
            choices = ", ".join((BASE_CONFIG, *RUN_CONFIGS))
            raise SettingsError(f"알 수 없는 구성 {config_name!r}. 가능한 값: {choices}")
        overlay_path = config_dir / f"{config_name}.toml"
        overlay = _read_toml(overlay_path)
        extra = set(overlay) - {"run"}
        if extra:
            raise SettingsError(
                f"{overlay_path.name}는 [run]만 덮어쓸 수 있습니다(INV-08). "
                f"추가 절: {sorted(extra)}"
            )
        data = {**data, "run": {**data.get("run", {}), **overlay.get("run", {})}}
        files.append(overlay_path)

    env = _merged_env(env_file, environ)
    return Settings(
        config_name=config_name,
        config_sha=sha256_of_files(files),
        models=_models(_section(data, "models")),
        chunking=_chunking(_section(data, "chunking")),
        retrieval=_retrieval(_section(data, "retrieval")),
        timeouts=_timeouts(_section(data, "timeouts")),
        paths=_paths(_section(data, "paths")),
        run=_run(_section(data, "run")),
        secrets=Secrets(
            openai_api_key=env.get("OPENAI_API_KEY") or None,
            database_url=env.get("DATABASE_URL") or None,
            database_url_test=env.get("DATABASE_URL_TEST") or None,
        ),
    )


def _read_toml(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise SettingsError(f"설정 파일이 없습니다: {path}")
    try:
        with path.open("rb") as handle:
            return tomllib.load(handle)
    except tomllib.TOMLDecodeError as exc:
        raise SettingsError(f"설정 파일 형식 오류: {path}: {exc}") from exc


def _merged_env(env_file: Path, environ: Mapping[str, str] | None) -> dict[str, str]:
    """`.env` 값 위에 환경변수를 덮어쓴다(환경변수가 우선)."""
    merged: dict[str, str] = {}
    if env_file.is_file():
        merged.update({k: v for k, v in dotenv_values(env_file).items() if v is not None})
    source = os.environ if environ is None else environ
    merged.update({k: source[k] for k in SECRET_KEYS if source.get(k)})
    return merged


def _section(data: dict[str, Any], name: str) -> dict[str, Any]:
    section = data.get(name)
    if not isinstance(section, dict):
        raise SettingsError(f"설정에 [{name}] 절이 없습니다.")
    return section


def _get(section: dict[str, Any], key: str, kind: type, where: str) -> Any:
    if key not in section:
        raise SettingsError(f"[{where}] {key} 값이 없습니다.")
    value = section[key]
    if kind is float and isinstance(value, int) and not isinstance(value, bool):
        value = float(value)
    if not isinstance(value, kind) or (kind is int and isinstance(value, bool)):
        raise SettingsError(f"[{where}] {key}는 {kind.__name__}여야 합니다: {value!r}")
    return value


def _positive_int(section: dict[str, Any], key: str, where: str) -> int:
    value = _get(section, key, int, where)
    if value <= 0:
        raise SettingsError(f"[{where}] {key}는 1 이상이어야 합니다: {value}")
    return value


def _models(s: dict[str, Any]) -> ModelSettings:
    device = _get(s, "reranker_device", str, "models")
    if device not in RERANKER_DEVICES:
        raise SettingsError(
            f"[models] reranker_device는 {RERANKER_DEVICES} 중 하나여야 합니다: {device}"
        )
    return ModelSettings(
        generation=_get(s, "generation", str, "models"),
        embedding=_get(s, "embedding", str, "models"),
        embedding_dim=_positive_int(s, "embedding_dim", "models"),
        reranker=_get(s, "reranker", str, "models"),
        reranker_device=device,
    )


def _chunking(s: dict[str, Any]) -> ChunkingSettings:
    max_chars = _positive_int(s, "max_chars", "chunking")
    overlap = _get(s, "overlap_chars", int, "chunking")
    if not 0 <= overlap < max_chars:
        raise SettingsError(
            f"[chunking] overlap_chars는 0 이상 max_chars 미만이어야 합니다: {overlap}"
        )
    return ChunkingSettings(max_chars=max_chars, overlap_chars=overlap)


def _retrieval(s: dict[str, Any]) -> RetrievalSettings:
    weights = _get(s, "weights", list, "retrieval")
    if len(weights) != 2 or not all(
        isinstance(w, int | float) and not isinstance(w, bool) and w >= 0 for w in weights
    ):
        raise SettingsError(f"[retrieval] weights는 0 이상 숫자 2개여야 합니다: {weights}")
    if sum(weights) <= 0:
        raise SettingsError("[retrieval] weights의 합은 0보다 커야 합니다.")
    return RetrievalSettings(
        n_vec=_positive_int(s, "n_vec", "retrieval"),
        n_bm25=_positive_int(s, "n_bm25", "retrieval"),
        n_fuse=_positive_int(s, "n_fuse", "retrieval"),
        k_opt=_positive_int(s, "k_opt", "retrieval"),
        rrf_c=_positive_int(s, "rrf_c", "retrieval"),
        weights=(float(weights[0]), float(weights[1])),
        question_list_max=_positive_int(s, "question_list_max", "retrieval"),
    )


def _timeouts(s: dict[str, Any]) -> TimeoutSettings:
    values = {k: _get(s, k, float, "timeouts") for k in ("generation_s", "rewrite_s", "judge_s")}
    for key, value in values.items():
        if value <= 0:
            raise SettingsError(f"[timeouts] {key}는 0보다 커야 합니다: {value}")
    return TimeoutSettings(**values)


def _paths(s: dict[str, Any]) -> PathSettings:
    return PathSettings(
        raw_dir=Path(_get(s, "raw_dir", str, "paths")),
        eval_dir=Path(_get(s, "eval_dir", str, "paths")),
        results_dir=Path(_get(s, "results_dir", str, "paths")),
    )


def _run(s: dict[str, Any]) -> RunSettings:
    mode = _get(s, "mode", str, "run")
    if mode not in RETRIEVAL_MODES:
        raise SettingsError(f"[run] mode는 {RETRIEVAL_MODES} 중 하나여야 합니다: {mode}")
    return RunSettings(mode=mode, use_rewrite=_get(s, "use_rewrite", bool, "run"))
