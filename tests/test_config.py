from pathlib import Path

import pytest
from pydantic import ValidationError

from radar.config import Config, load_config

REPO_ROOT = Path(__file__).resolve().parents[1]


def minimal(**overrides):
    data = {"categories": ["cs.CV"], "seed_papers": [{"id": "2304.07193"}]}
    data.update(overrides)
    return data


def test_repo_config_is_valid():
    cfg = load_config(REPO_ROOT / "config.yaml")
    assert cfg.categories
    assert cfg.seed_papers


def test_defaults_applied():
    cfg = Config.model_validate(minimal())
    assert cfg.ranking.list_size == 10
    assert cfg.ingest.request_delay_seconds >= 3.0


@pytest.mark.parametrize("pid", ["2304.07193", "2007.04612", "1501.0001", "hep-th/9901001"])
def test_valid_seed_ids(pid):
    Config.model_validate(minimal(seed_papers=[{"id": pid}]))


@pytest.mark.parametrize("pid", ["2304.07193v2", "arXiv:2304.07193", "23040.7193", ""])
def test_invalid_seed_ids(pid):
    with pytest.raises(ValidationError):
        Config.model_validate(minimal(seed_papers=[{"id": pid}]))


def test_duplicate_seeds_rejected():
    with pytest.raises(ValidationError):
        Config.model_validate(minimal(seed_papers=[{"id": "2304.07193"}, {"id": "2304.07193"}]))


def test_invalid_category_rejected():
    with pytest.raises(ValidationError):
        Config.model_validate(minimal(categories=["computer vision"]))


def test_unknown_key_rejected():
    with pytest.raises(ValidationError):
        Config.model_validate(minimal(categoriez=["cs.CV"]))


def test_request_delay_below_arxiv_minimum_rejected():
    with pytest.raises(ValidationError):
        Config.model_validate(minimal(ingest={"request_delay_seconds": 1.0}))


def test_exploration_range_must_start_below_top_list():
    with pytest.raises(ValidationError):
        Config.model_validate(
            minimal(ranking={"list_size": 30, "exploration_rank_range": [20, 100]})
        )


def test_duplicate_keywords_rejected_case_insensitive():
    with pytest.raises(ValidationError):
        Config.model_validate(minimal(keywords=["Segmentation", "segmentation"]))
