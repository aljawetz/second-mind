"""guard.py — the graded-work classifier (RAG gaps plan, task 7). These use
toy vectors and a fake embed, so no model files are loaded."""

import json

import numpy as np
import pytest

import guard


def _separable(n=40, dim=8, seed=0):
    rng = np.random.default_rng(seed)
    X = rng.normal(size=(n * 2, dim))
    margin = X[:, 0] + 0.5 * X[:, 1]
    X = X[np.abs(margin) > 0.3][:n]  # no points on the boundary itself
    y = (X[:, 0] + 0.5 * X[:, 1] > 0).astype(float)
    return X, y


def test_fit_learns_a_separable_rule():
    X, y = _separable()
    w, b = guard.fit(X, y, l2=0.1)
    predicted = guard.predict(w, b, X) > 0.5
    assert (predicted == y.astype(bool)).mean() == 1.0


def test_fit_scores_are_probabilities():
    X, y = _separable()
    w, b = guard.fit(X, y)
    p = guard.predict(w, b, X)
    assert ((p > 0) & (p < 1)).all()


def test_stronger_l2_gives_smaller_weights():
    X, y = _separable()
    weak, _ = guard.fit(X, y, l2=0.01)
    strong, _ = guard.fit(X, y, l2=10.0)
    assert np.linalg.norm(strong) < np.linalg.norm(weak)


def test_threshold_for_false_alarm_rate_keeps_normal_scores_under_it():
    normal = np.array([0.01, 0.05, 0.1, 0.2, 0.3, 0.4, 0.45, 0.5, 0.55, 0.6])
    t = guard.threshold_for(normal, max_false_alarm=0.1)
    assert (normal >= t).mean() <= 0.1
    # and it's no higher than it needs to be: the next normal score down flags
    assert t <= 0.6 + 1e-9


def _write(tmp_path, w, b, threshold):
    path = tmp_path / "guard_weights.json"
    path.write_text(json.dumps({"weights": list(w), "bias": b, "threshold": threshold}))
    return path


def test_load_scores_with_the_embedding_and_flags_above_threshold(tmp_path):
    path = _write(tmp_path, [1.0, 0.0], 0.0, 0.7)
    vectors = {"solve my exam": [3.0, 0.0], "when is the exam": [-3.0, 0.0]}
    g = guard.load(lambda text: vectors[text], path)
    assert g.score("solve my exam") == pytest.approx(1 / (1 + np.exp(-3)))
    assert g.flags("solve my exam") is True
    assert g.flags("when is the exam") is False


def test_load_without_a_weights_file_is_none(tmp_path):
    assert guard.load(lambda text: [0.0], tmp_path / "missing.json") is None


def test_shipped_weights_match_the_embedding_size():
    from embeddings import EMBEDDING_DIM

    saved = json.loads(guard.WEIGHTS_FILE.read_text())
    assert len(saved["weights"]) == EMBEDDING_DIM
    assert 0 < saved["threshold"] < 1
