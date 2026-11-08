"""Help-center search.

BM25 over paragraph-sized chunks. For a dozen articles a vector database is
overkill, and lexical search has the nice property of being explainable:
you can see exactly which words matched.
"""

from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

HELP_DIR = Path(__file__).parent / "seed" / "help_center"

STOPWORDS = set(
    """a an and are as at be but by can do does for from get got have how i if in into is it
    its just me my no not of on or our so than that the their them then there these they this
    to up us was we what when where which who why will with you your yours""".split()
)

_SYNONYMS = {
    "refund": ["return"],
    "refunds": ["return"],
    "broken": ["defect", "warranty"],
    "leaking": ["defect", "warranty"],
    "charged": ["charge"],
    "charges": ["charge"],
    "package": ["tracking", "shipped"],
    "parcel": ["tracking", "shipped"],
    "late": ["tracking", "shipping"],
    "cancel": ["cancel"],
    "password": ["sign"],
    "fridge": ["refrigerate", "store"],
    "sour": ["grind", "finer"],
    "bitter": ["grind", "coarser"],
    "pressure": ["descale"],
    "dented": ["damaged"],
    "crushed": ["damaged"],
}


def tokenize(text: str) -> list[str]:
    words = re.findall(r"[a-z0-9]+", text.lower())
    out: list[str] = []
    for w in words:
        if w in STOPWORDS or len(w) < 2:
            continue
        out.append(_stem(w))
        out.extend(_stem(s) for s in _SYNONYMS.get(w, []))
    return out


def _stem(w: str) -> str:
    # deliberately tiny stemmer; enough to match "charges"/"charged"/"charge"
    for suffix in ("ing", "ed", "es", "s"):
        if len(w) > 4 and w.endswith(suffix):
            return w[: -len(suffix)]
    return w


@dataclass(frozen=True)
class Article:
    slug: str
    title: str
    category: str
    body: str


@dataclass(frozen=True)
class Hit:
    slug: str
    title: str
    snippet: str
    score: float


def parse_article(path: Path) -> Article:
    text = path.read_text()
    meta: dict[str, str] = {}
    body = text
    if text.startswith("---"):
        _, front, body = text.split("---", 2)
        for line in front.strip().splitlines():
            key, _, value = line.partition(":")
            meta[key.strip()] = value.strip()
    return Article(
        slug=path.stem,
        title=meta.get("title", path.stem),
        category=meta.get("category", "general"),
        body=body.strip(),
    )


class HelpCenter:
    def __init__(self, articles: list[Article], k1: float = 1.4, b: float = 0.75):
        self.articles = {a.slug: a for a in articles}
        self.k1, self.b = k1, b
        self.chunks: list[tuple[str, str, list[str]]] = []  # (slug, text, tokens)
        for a in articles:
            for para in re.split(r"\n\s*\n", a.body):
                para = para.strip()
                if para:
                    # title tokens on every chunk so short paragraphs still match their topic
                    self.chunks.append((a.slug, para, tokenize(a.title + " " + para)))
        self.avgdl = sum(len(t) for *_, t in self.chunks) / max(len(self.chunks), 1)
        df: Counter[str] = Counter()
        for *_, toks in self.chunks:
            df.update(set(toks))
        n = len(self.chunks)
        self.idf = {term: math.log(1 + (n - f + 0.5) / (f + 0.5)) for term, f in df.items()}

    def _score(self, q: list[str], toks: list[str]) -> float:
        tf = Counter(toks)
        dl = len(toks)
        score = 0.0
        for term in q:
            if term not in tf:
                continue
            f = tf[term]
            denom = f + self.k1 * (1 - self.b + self.b * dl / self.avgdl)
            score += self.idf.get(term, 0.0) * f * (self.k1 + 1) / denom
        return score

    def search(self, query: str, k: int = 3) -> list[Hit]:
        q = tokenize(query)
        best: dict[str, tuple[float, str]] = {}
        for slug, text, toks in self.chunks:
            s = self._score(q, toks)
            if s > 0 and s > best.get(slug, (0.0, ""))[0]:
                best[slug] = (s, text)
        ranked = sorted(best.items(), key=lambda kv: kv[1][0], reverse=True)[:k]
        return [
            Hit(slug=slug, title=self.articles[slug].title, snippet=text, score=round(score, 3))
            for slug, (score, text) in ranked
        ]

    def get(self, slug: str) -> Article | None:
        return self.articles.get(slug)


@lru_cache(maxsize=1)
def help_center() -> HelpCenter:
    return HelpCenter([parse_article(p) for p in sorted(HELP_DIR.glob("*.md"))])
