import pytest

from radar.models import split_arxiv_id


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("2304.07193v2", ("2304.07193", 2)),
        ("2304.07193", ("2304.07193", 1)),
        ("2611.01234v12", ("2611.01234", 12)),
        ("http://arxiv.org/abs/2304.07193v2", ("2304.07193", 2)),
        ("https://arxiv.org/abs/2304.07193v3", ("2304.07193", 3)),
        ("http://export.arxiv.org/abs/2304.07193v1", ("2304.07193", 1)),
        ("arXiv:2304.07193v1", ("2304.07193", 1)),
        ("cs/0112017v1", ("cs/0112017", 1)),
        ("math.GT/0309136v2", ("math.GT/0309136", 2)),
        ("  2304.07193v2 \n", ("2304.07193", 2)),
    ],
)
def test_split_arxiv_id(raw, expected):
    assert split_arxiv_id(raw) == expected


@pytest.mark.parametrize(
    "raw", ["", "2304.071", "2304.07193v", "http://arxiv.org/api/errors#bad", "not-an-id"]
)
def test_split_arxiv_id_rejects(raw):
    with pytest.raises(ValueError):
        split_arxiv_id(raw)
