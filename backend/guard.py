"""Graded-work guard: a logistic regression on a question's embedding that
says when a chat turn looks like a request to do graded work (solve an exam,
quiz, graded assignment or lab), so chat.answer can add a stricter rule to
that turn's system prompt instead of relying on the general rule alone.
RAG gaps plan (docs/plans/2026-11-09-rag-course-gaps.md), task 7.

The model is the local bge-small embedding search already loads, plus 384
weights and a bias in guard_weights.json, trained and checked by
scripts/guard_train.py. Plain numpy: scikit-learn isn't a dependency of the
app, and one Newton fit on a few hundred questions doesn't need it.
"""

import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import numpy as np

WEIGHTS_FILE = Path(__file__).parent / "guard_weights.json"


def _sigmoid(z: np.ndarray) -> np.ndarray:
    return 1.0 / (1.0 + np.exp(-np.clip(z, -30, 30)))


def fit(X: np.ndarray, y: np.ndarray, l2: float = 1.0, iterations: int = 50) -> tuple[np.ndarray, float]:
    """L2-regularized logistic regression by Newton's method. The bias isn't
    regularized. Returns (weights, bias)."""
    X = np.asarray(X, dtype=float)
    y = np.asarray(y, dtype=float)
    n, dim = X.shape
    Xb = np.hstack([X, np.ones((n, 1))])
    theta = np.zeros(dim + 1)
    penalty = np.full(dim + 1, l2)
    penalty[-1] = 0.0
    for _ in range(iterations):
        p = _sigmoid(Xb @ theta)
        gradient = Xb.T @ (p - y) + penalty * theta
        hessian = (Xb * (p * (1 - p))[:, None]).T @ Xb + np.diag(penalty) + 1e-9 * np.eye(dim + 1)
        step = np.linalg.solve(hessian, gradient)
        theta -= step
        if np.abs(step).max() < 1e-8:
            break
    return theta[:-1], float(theta[-1])


def predict(weights: np.ndarray, bias: float, X: np.ndarray) -> np.ndarray:
    return _sigmoid(np.asarray(X, dtype=float) @ np.asarray(weights, dtype=float) + bias)


def threshold_for(normal_scores: np.ndarray, max_false_alarm: float) -> float:
    """The lowest threshold at which at most `max_false_alarm` of these
    normal questions' scores reach it (a score >= threshold flags)."""
    scores = np.sort(np.asarray(normal_scores, dtype=float))[::-1]
    allowed = int(np.floor(max_false_alarm * len(scores)))
    if allowed >= len(scores):
        return 0.0
    # Just above the highest normal score that must not flag.
    return float(np.nextafter(scores[allowed], np.inf))


@dataclass
class Guard:
    weights: np.ndarray
    bias: float
    threshold: float
    embed: Callable[[str], list[float]]

    def score(self, text: str) -> float:
        return float(predict(self.weights, self.bias, np.asarray(self.embed(text))))

    def flags(self, text: str) -> bool:
        return self.score(text) >= self.threshold


def load(embed: Callable[[str], list[float]], path: Path = WEIGHTS_FILE) -> Guard | None:
    """The guard from `path`, or None when there's no weights file (the
    chat then runs on its general rule alone)."""
    if not path.exists():
        print(f"guard: no weights at {path}; graded-work guard off", file=sys.stderr)
        return None
    saved = json.loads(path.read_text())
    return Guard(np.asarray(saved["weights"], dtype=float), float(saved["bias"]), float(saved["threshold"]), embed)
