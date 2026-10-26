"""Local cross-encoder reranker (Sprint 8).

Scores each (question, chunk) pair together with cross-encoder/ms-marco-MiniLM-L-6-v2
(88MB, 6 layers),
run with onnxruntime + tokenizers only, the same way embeddings.py runs
bge-small: no torch, no network, no API key at query time.

A cross-encoder reads the question and the chunk at the same time, so it
can tell "the midterm is on Oct 14" apart from "midterm coding question"
better than either keyword or meaning search alone. Its raw output is one
logit per pair; sigmoid turns that into a 0 to 1 relevance score that
means the same thing for every course, which is what a minimum score
cutoff needs (BM25 scores do not have that property, see generation.py).

Model files are not in this repo (see .gitignore). Run
scripts/convert_reranker_model.py once. If the files are missing,
load_reranker() returns None and search falls back to rank fusion only.
"""

import logging
from pathlib import Path

import numpy as np

logger = logging.getLogger(__name__)

MODEL_DIR = Path(__file__).parent / "models" / "ms-marco-MiniLM-L-6-v2-onnx"
MAX_SEQ_LENGTH = 512  # the model's own tokenizer_config.json model_max_length
BATCH_SIZE = 8


def sigmoid(x: np.ndarray) -> np.ndarray:
    return 1.0 / (1.0 + np.exp(-x))


class OnnxCrossEncoder:
    """score(query, passages) -> one 0 to 1 relevance score per passage."""

    def __init__(self, model_dir: Path = MODEL_DIR) -> None:
        import onnxruntime as ort
        from tokenizers import Tokenizer

        self._tokenizer = Tokenizer.from_file(str(model_dir / "tokenizer.json"))
        # Long chunks are cut, not rejected. Only the passage side is cut
        # in practice, since questions are short.
        self._tokenizer.enable_truncation(max_length=MAX_SEQ_LENGTH)
        self._tokenizer.enable_padding()
        self._session = ort.InferenceSession(str(model_dir / "model.onnx"))
        self._input_names = {i.name for i in self._session.get_inputs()}

    def score(self, query: str, passages: list[str]) -> list[float]:
        scores: list[float] = []
        for start in range(0, len(passages), BATCH_SIZE):
            batch = passages[start : start + BATCH_SIZE]
            encodings = self._tokenizer.encode_batch([(query, p) for p in batch])
            feeds = {
                "input_ids": np.array([e.ids for e in encodings], dtype=np.int64),
                "attention_mask": np.array([e.attention_mask for e in encodings], dtype=np.int64),
            }
            if "token_type_ids" in self._input_names:
                feeds["token_type_ids"] = np.array([e.type_ids for e in encodings], dtype=np.int64)
            logits = self._session.run(None, feeds)[0].reshape(-1)
            scores.extend(sigmoid(logits).tolist())
        return scores


_cached: dict[Path, OnnxCrossEncoder | None] = {}


def load_reranker(model_dir: Path = MODEL_DIR) -> OnnxCrossEncoder | None:
    """The reranker, loaded once per process, or None if the model files
    are missing or fail to load. None means "skip reranking"; it is never
    an error, so a fresh checkout or CI without the model still searches."""
    if model_dir not in _cached:
        if not (model_dir / "model.onnx").exists() or not (model_dir / "tokenizer.json").exists():
            logger.warning("Reranker model not found at %s; using rank fusion only", model_dir)
            _cached[model_dir] = None
        else:
            try:
                _cached[model_dir] = OnnxCrossEncoder(model_dir)
            except Exception:  # a broken model file must not break search
                logger.exception("Reranker failed to load; using rank fusion only")
                _cached[model_dir] = None
    return _cached[model_dir]
