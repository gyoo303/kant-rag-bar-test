"""TKT-BE-M1-01: 설정 읽기 (ADR-003, 04-interfaces-api §6)."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from lawqa.shared.settings import SettingsError, load_settings

REPO_CONFIG = Path(__file__).resolve().parents[3] / "config"
NO_ENV: dict[str, str] = {}


@pytest.fixture
def config_dir(tmp_path: Path) -> Path:
    """저장소 config/를 임시 폴더로 복사해 시험마다 고칠 수 있게 한다."""
    target = tmp_path / "config"
    shutil.copytree(REPO_CONFIG, target)
    return target


def _load(config_dir: Path, name: str = "base", environ: dict[str, str] | None = None):
    return load_settings(
        name,
        config_dir=config_dir,
        env_file=config_dir / "missing.env",
        environ=NO_ENV if environ is None else environ,
    )


def test_load_settings_repo_base_reads_all_sections() -> None:
    settings = load_settings(
        "base", config_dir=REPO_CONFIG, env_file=Path("missing.env"), environ={}
    )

    assert settings.models.generation == "gpt-6-luna"
    assert settings.models.embedding == "text-embedding-3-small"
    assert settings.models.embedding_dim == 1536
    assert settings.chunking.max_chars == 1500
    assert settings.retrieval.weights == (0.5, 0.5)
    assert settings.paths.raw_dir == Path("law_collector/data")


@pytest.mark.parametrize(
    ("name", "mode", "use_rewrite"),
    [("A", "A", False), ("B", "B", False), ("C", "C", False), ("C+R", "C", True)],
)
def test_load_settings_run_config_overrides_only_run(
    name: str, mode: str, use_rewrite: bool
) -> None:
    base = load_settings("base", config_dir=REPO_CONFIG, env_file=Path("missing.env"), environ={})
    settings = load_settings(name, config_dir=REPO_CONFIG, env_file=Path("missing.env"), environ={})

    assert (settings.run.mode, settings.run.use_rewrite) == (mode, use_rewrite)
    # INV-08: 구성끼리 다른 값은 [run]뿐
    assert settings.models == base.models
    assert settings.retrieval == base.retrieval
    assert settings.timeouts == base.timeouts


def test_config_sha_changes_when_run_config_file_changes(config_dir: Path) -> None:
    before = _load(config_dir, "C").config_sha
    (config_dir / "C.toml").write_text('[run]\nmode = "C"\nuse_rewrite = true\n', encoding="utf-8")

    after = _load(config_dir, "C").config_sha

    assert before != after


def test_config_sha_changes_when_base_file_changes(config_dir: Path) -> None:
    before = _load(config_dir, "A").config_sha
    base = config_dir / "base.toml"
    base.write_text(
        base.read_text(encoding="utf-8").replace("k_opt = 4", "k_opt = 5"), encoding="utf-8"
    )

    assert _load(config_dir, "A").config_sha != before


def test_config_sha_differs_between_configs() -> None:
    shas = {
        name: load_settings(
            name, config_dir=REPO_CONFIG, env_file=Path("missing.env"), environ={}
        ).config_sha
        for name in ("A", "B", "C", "C+R")
    }

    assert len(set(shas.values())) == 4


def test_load_settings_rejects_overlay_with_other_sections(config_dir: Path) -> None:
    (config_dir / "B.toml").write_text(
        '[run]\nmode = "B"\nuse_rewrite = false\n[models]\ngeneration = "other"\n', encoding="utf-8"
    )

    with pytest.raises(SettingsError, match="INV-08"):
        _load(config_dir, "B")


def test_load_settings_rejects_unknown_config_name(config_dir: Path) -> None:
    with pytest.raises(SettingsError, match="알 수 없는 구성"):
        _load(config_dir, "D")


def test_load_settings_rejects_overlap_not_smaller_than_max(config_dir: Path) -> None:
    base = config_dir / "base.toml"
    base.write_text(
        base.read_text(encoding="utf-8").replace("overlap_chars = 150", "overlap_chars = 1500"),
        encoding="utf-8",
    )

    with pytest.raises(SettingsError, match="overlap_chars"):
        _load(config_dir)


def test_load_settings_rejects_unknown_reranker_device(config_dir: Path) -> None:
    base = config_dir / "base.toml"
    base.write_text(
        base.read_text(encoding="utf-8").replace(
            'reranker_device = "cuda"', 'reranker_device = "tpu"'
        ),
        encoding="utf-8",
    )

    with pytest.raises(SettingsError, match="reranker_device"):
        _load(config_dir)


def test_load_settings_missing_base_file_raises(tmp_path: Path) -> None:
    with pytest.raises(SettingsError, match="설정 파일이 없습니다"):
        _load(tmp_path)


def test_secrets_environ_overrides_env_file_and_hides_values(config_dir: Path) -> None:
    env_file = config_dir / "test.env"
    env_file.write_text(
        "OPENAI_API_KEY=from-file\nDATABASE_URL=postgresql://file\n", encoding="utf-8"
    )

    settings = load_settings(
        "base", config_dir=config_dir, env_file=env_file, environ={"OPENAI_API_KEY": "from-env"}
    )

    assert settings.secrets.require("openai_api_key") == "from-env"
    assert settings.secrets.require("database_url") == "postgresql://file"
    assert "from-env" not in repr(settings)
    assert "postgresql://file" not in repr(settings)


def test_secrets_require_missing_value_raises_without_value(config_dir: Path) -> None:
    settings = _load(config_dir)

    with pytest.raises(SettingsError, match="OPENAI_API_KEY"):
        settings.secrets.require("openai_api_key")
