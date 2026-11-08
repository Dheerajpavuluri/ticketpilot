import pytest

from app.retrieval import help_center, tokenize


@pytest.mark.parametrize(
    "query,slug",
    [
        ("where is my package, tracking not updating", "track-order"),
        ("I want a refund for my grinder", "returns-policy"),
        ("how often should I descale", "descaling"),
        ("my shots taste sour", "grinder-calibration"),
        ("I was charged twice", "billing"),
        ("skip my subscription box next month", "subscriptions"),
        ("forgot my password", "account"),
        ("box arrived crushed", "damaged-item"),
    ],
)
def test_search_finds_the_right_article(query, slug):
    hits = help_center().search(query)
    assert slug in [h.slug for h in hits[:2]]


def test_no_match_returns_empty():
    assert help_center().search("zzzz qqqq") == []


def test_tokenize_drops_stopwords_and_stems():
    toks = tokenize("The charges were charged to my card")
    assert "the" not in toks
    assert toks.count("charg") == 2


def test_hits_are_deduplicated_per_article():
    hits = help_center().search("return refund return policy refund")
    slugs = [h.slug for h in hits]
    assert len(slugs) == len(set(slugs))
