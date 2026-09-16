"""implementation-plan.md Step 4. Needs models/bge-small-en-v1.5-onnx/ —
run scripts/convert_embedding_model.py once first.

The stronger check (ONNX output matches the sentence-transformers/torch
reference, cosine similarity ~1.0) was done once by hand during development,
not here — re-deriving it in every test run would reintroduce torch as a
recurring dependency, working against the whole point of this step.
"""

import numpy as np
import pytest

from embeddings import EMBEDDING_DIM, MODEL_DIR, OnnxBgeEmbedding

pytestmark = pytest.mark.skipif(
    not MODEL_DIR.exists(), reason="run scripts/convert_embedding_model.py first"
)


@pytest.fixture(scope="module")
def embedding():
    return OnnxBgeEmbedding()


def test_text_embedding_dimension(embedding):
    vec = embedding._get_text_embedding("This is a test sentence about retrieval systems.")
    assert len(vec) == EMBEDDING_DIM


def test_query_embedding_dimension(embedding):
    vec = embedding._get_query_embedding("What is retrieval?")
    assert len(vec) == EMBEDDING_DIM


def test_embedding_is_unit_normalized(embedding):
    vec = embedding._get_text_embedding("Another test sentence.")
    assert np.isclose(np.linalg.norm(vec), 1.0, atol=1e-5)


def test_batch_matches_individual(embedding):
    texts = ["First sentence.", "Second sentence."]
    batch = embedding._get_text_embeddings(texts)
    individual = [embedding._get_text_embedding(t) for t in texts]
    assert np.allclose(batch, individual)
