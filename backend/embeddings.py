"""Local, torch-free embeddings — implementation-plan.md Step 4.

Wraps the pre-converted ONNX model directly via onnxruntime + tokenizers,
not LlamaIndex's own HuggingFaceEmbedding (sentence-transformers/torch) or
its huggingface-optimum wrapper (still pulls torch transitively via
optimum, confirmed by installing it — rag-pipeline.md §3). CLS-token
pooling, L2-normalized, no query instruction prefix — verified to match
the sentence-transformers reference bit-for-bit (cosine similarity
~1.0000) for the same input, and sentence-transformers' own packaged
config for this model has empty query/document prompts, so there's
nothing to replicate there either.

Model files aren't in this repo (see .gitignore) — run
scripts/convert_embedding_model.py once before using this.
"""

from pathlib import Path
from typing import Any

import numpy as np
import onnxruntime as ort
from llama_index.core.embeddings import BaseEmbedding
from tokenizers import Tokenizer

MODEL_DIR = Path(__file__).parent / "models" / "bge-small-en-v1.5-onnx"
EMBEDDING_DIM = 384


class OnnxBgeEmbedding(BaseEmbedding):
    """`bge-small-en-v1.5`, ONNX Runtime only — no torch at any point."""

    def __init__(self, model_dir: Path = MODEL_DIR, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._tokenizer = Tokenizer.from_file(str(model_dir / "tokenizer.json"))
        self._session = ort.InferenceSession(str(model_dir / "model.onnx"))

    def _embed(self, text: str) -> list[float]:
        enc = self._tokenizer.encode(text)
        input_ids = np.array([enc.ids], dtype=np.int64)
        attention_mask = np.array([enc.attention_mask], dtype=np.int64)
        token_type_ids = np.zeros_like(input_ids)

        outputs = self._session.run(
            None,
            {"input_ids": input_ids, "attention_mask": attention_mask, "token_type_ids": token_type_ids},
        )
        cls_embedding = outputs[0][:, 0]  # CLS-token pooling, matches this model's reference implementation
        normalized = cls_embedding / np.linalg.norm(cls_embedding, axis=1, keepdims=True)
        return normalized[0].tolist()

    def _get_query_embedding(self, query: str) -> list[float]:
        return self._embed(query)

    def _get_text_embedding(self, text: str) -> list[float]:
        return self._embed(text)

    def _get_text_embeddings(self, texts: list[str]) -> list[list[float]]:
        return [self._embed(t) for t in texts]

    async def _aget_query_embedding(self, query: str) -> list[float]:
        return self._get_query_embedding(query)

    async def _aget_text_embedding(self, text: str) -> list[float]:
        return self._get_text_embedding(text)
