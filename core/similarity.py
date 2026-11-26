"""
similarity.py
-------------
Text similarity between a resume and a job description, with two backends.

* tfidf (default): word-overlap cosine similarity. Needs nothing beyond
  scikit-learn, runs offline and instantly. It matches words, not meaning.
* embeddings: sentence embeddings, so "built scalable APIs" lands close to
  "REST API development". Needs `pip install sentence-transformers` and a
  one-time model download. Turn it on with SIMILARITY_BACKEND=embeddings
  (model: EMBEDDING_MODEL, default all-MiniLM-L6-v2).

If the embeddings backend cannot start (package or model missing), the system
falls back to tfidf and reports that, so scoring never fails because of it.

Both backends return a 0-100 similarity already scaled for the final score,
plus the backend that actually produced it.
"""

import logging
import os

from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

logger = logging.getLogger("resume_screening.similarity")

TFIDF_SCALE = 2.5            # raw TF-IDF cosine is low even for good matches
EMB_FLOOR, EMB_CEIL = 0.15, 0.65   # cosine range mapped to 0-100 (starting point, see docs)
CHUNK_WORDS = 120            # embedding models read only a few hundred tokens

_encoder = None              # callable: list[str] -> list[list[float]]
_encoder_failed = False


def requested_backend() -> str:
    return "embeddings" if os.environ.get("SIMILARITY_BACKEND", "tfidf").lower() == "embeddings" else "tfidf"


def set_encoder(fn):
    """Install an encoder (used by tests, or to plug in another model)."""
    global _encoder, _encoder_failed
    _encoder, _encoder_failed = fn, False


def _load_encoder():
    global _encoder, _encoder_failed
    if _encoder is not None or _encoder_failed:
        return _encoder
    try:
        from sentence_transformers import SentenceTransformer  # optional dependency
        model = SentenceTransformer(os.environ.get("EMBEDDING_MODEL", "all-MiniLM-L6-v2"))
        _encoder = lambda texts: model.encode(texts, normalize_embeddings=True)  # noqa: E731
    except Exception as exc:  # noqa: BLE001 - any failure means: use tfidf
        _encoder_failed = True
        logger.warning("Embeddings backend unavailable (%s). Using tfidf.", exc)
    return _encoder


def tfidf_similarity(resume_text: str, jd_text: str) -> float:
    """Raw TF-IDF cosine similarity, 0-100."""
    vectorizer = TfidfVectorizer(stop_words="english", max_features=5000, ngram_range=(1, 2))
    try:
        matrix = vectorizer.fit_transform([jd_text, resume_text])
    except ValueError:
        return 0.0  # both documents empty after stop-word removal
    sim = cosine_similarity(matrix[0:1], matrix[1:2])[0][0]
    return max(0.0, min(1.0, sim)) * 100


def _chunks(text: str) -> list:
    words = text.split()
    return [" ".join(words[i:i + CHUNK_WORDS]) for i in range(0, max(len(words), 1), CHUNK_WORDS)] or [""]


def embedding_similarity(resume_text: str, jd_text: str, encoder) -> float:
    """
    Raw cosine, 0-100 on the model's own scale: each part of the job description
    is matched to its closest part of the resume, and the matches are averaged.
    """
    jd_parts, cv_parts = _chunks(jd_text), _chunks(resume_text)
    vectors = [list(map(float, v)) for v in encoder(jd_parts + cv_parts)]
    jd_v, cv_v = vectors[:len(jd_parts)], vectors[len(jd_parts):]

    def cos(a, b):
        na = sum(x * x for x in a) ** 0.5
        nb = sum(x * x for x in b) ** 0.5
        return sum(x * y for x, y in zip(a, b)) / (na * nb) if na and nb else 0.0

    best = [max(cos(j, c) for c in cv_v) for j in jd_v]
    return max(0.0, min(1.0, sum(best) / len(best))) * 100


def compute(resume_text: str, jd_text: str):
    """Return (similarity 0-100 for the final score, raw 0-100, backend used)."""
    if requested_backend() == "embeddings":
        encoder = _load_encoder()
        if encoder is not None:
            raw = embedding_similarity(resume_text, jd_text, encoder)
            scaled = (raw / 100 - EMB_FLOOR) / (EMB_CEIL - EMB_FLOOR) * 100
            return max(0.0, min(100.0, scaled)), raw, "embeddings"
    raw = tfidf_similarity(resume_text, jd_text)
    return min(100.0, raw * TFIDF_SCALE), raw, "tfidf"
