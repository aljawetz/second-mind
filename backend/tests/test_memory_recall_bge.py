"""Recall with the real embedding model (bge-small-en-v1.5), not the
word-hashing stand-in the other memory tests use.

Guards the bug seen in the app on 2026-10-06: every answer listed every
memory under "Used what you told me earlier". Real BGE scores unrelated
short sentences 0.41-0.61 against a question, so the first 0.5 cutoff let
nearly everything through. The stand-in embedder can't show this; only the
real model can.
"""

from datetime import datetime, timezone

import pytest

from embeddings import MODEL_DIR
from memory import recall
from memory.store import MemoryStore

pytestmark = pytest.mark.skipif(not MODEL_DIR.exists(), reason="run scripts/convert_embedding_model.py first")

NOW = datetime(2026, 10, 6, 12, 0, tzinfo=timezone.utc)
FACTS = {
    "team": "The student is on team 4 with Priya and Ken.",
    "java": "The student wants code examples in Java.",
    "auditing": "The student is auditing the course.",
    "email": "The student finished part 1 of Assignment 3 and is stuck mocking the email service.",
    "missed": "On 2026-09-22 the student missed Class #5.",
    "fraud": "The student's project is a fraud detection system.",
}

UNRELATED = [
    "When is the midterm?",
    "What is combinatorial testing?",
    "What is retrieval-augmented generation?",
    "What's the late policy?",
]
RELATED = [
    ("Which team am I on?", "team"),
    ("How do I mock the email service?", "email"),
    ("What did I miss in class?", "missed"),
    ("What should our fraud model's first milestone cover?", "fraud"),
    ("Show me how to stub a repository class.", "java"),
]


@pytest.fixture(scope="module")
def setup(tmp_path_factory):
    import memory_jobs

    store = MemoryStore(tmp_path_factory.mktemp("bge") / "memory.db")
    ids = {
        key: store.add(kind="fact", text=text, importance=3, embedding=memory_jobs.embed(text), created_at=NOW)
        for key, text in FACTS.items()
    }
    yield store, ids, memory_jobs.embed
    store.close()


@pytest.mark.parametrize("question", UNRELATED)
def test_a_question_about_something_else_recalls_nothing(setup, question):
    store, _, embed = setup

    assert recall.recall(question, store=store, embed=embed, now=NOW) == []


@pytest.mark.parametrize("question, key", RELATED)
def test_a_related_question_recalls_its_memory_first(setup, question, key):
    store, ids, embed = setup

    hits = recall.recall(question, store=store, embed=embed, now=NOW)

    assert hits and hits[0].memory.id == ids[key], [h.memory.text for h in hits]
