import pytest

from backend.retrieval.hybrid import RRF_K, rrf_fuse, tokenize


def test_rrf_hand_computed_order():
    # a: 1/61; b: 1/62 + 1/61; c: 1/63 + 1/62; d: 1/63   ->  b > c > a > d
    fused = rrf_fuse([["a", "b", "c"], ["b", "c", "d"]])
    assert [d for d, _ in fused] == ["b", "c", "a", "d"]
    scores = dict(fused)
    assert scores["b"] == pytest.approx(1 / 62 + 1 / 61)
    assert scores["d"] == pytest.approx(1 / (RRF_K + 3))


def test_rrf_rewards_agreement_over_a_single_top_rank():
    # "x" is first in one list only; "y" is second in both -> y wins
    fused = rrf_fuse([["x", "y"], ["z", "y"]])
    assert fused[0][0] == "y"


def test_rrf_empty_and_single_list():
    assert rrf_fuse([]) == []
    assert [d for d, _ in rrf_fuse([["a", "b"]])] == ["a", "b"]


def test_tokenize_drops_stopwords_keeps_numbers():
    assert tokenize("Repayment of the Borrowings of ₹25,000.50 million") == \
        ["repayment", "borrowings", "25", "000.50", "million"]
