import pytest

import reranker


@pytest.fixture(autouse=True)
def _no_default_reranker(monkeypatch, request):
    """Tests get rank fusion only unless they pass a reranker in, so the
    result does not depend on whether this machine has the reranker model
    (CI does not). Tests marked real_reranker load the real one."""
    if "real_reranker" not in request.keywords:
        monkeypatch.setattr(reranker, "load_reranker", lambda *args, **kwargs: None)
