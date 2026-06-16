"""Tests du wrapper embeddings (code_index.embed) avec un client Mistral factice."""
from __future__ import annotations

import pytest

from code_index import embed
from code_index.embed import Throttle, _make_batches, embed_texts


def test_make_batches_respects_char_budget() -> None:
    # 5 textes de 30 caractères, budget 100 → lots de 3 max (90 ≤ 100, 120 > 100).
    texts = ["x" * 30] * 5
    batches = _make_batches(texts, batch_size=99, max_batch_chars=100)
    assert [len(b) for b in batches] == [3, 2]


def test_make_batches_oversized_single_text_isolated() -> None:
    batches = _make_batches(["a" * 500, "b"], batch_size=99, max_batch_chars=100)
    assert [len(b) for b in batches] == [1, 1]


class _Item:
    def __init__(self, vec: list[float]) -> None:
        self.embedding = vec


class _Resp:
    def __init__(self, items: list[_Item]) -> None:
        self.data = items


class _FakeEmbeddings:
    def __init__(self) -> None:
        self.calls: list[tuple[list[str], dict]] = []

    def create(self, model: str, inputs: list[str], **kw):  # noqa: ANN003
        self.calls.append((inputs, kw))
        return _Resp([_Item([float(len(t)), 1.0]) for t in inputs])


class _FakeClient:
    def __init__(self) -> None:
        self.embeddings = _FakeEmbeddings()


def test_batches_and_truncates() -> None:
    client = _FakeClient()
    vecs = embed_texts(client, ["aa", "bbb", "cccc"], model="m", dim=None, batch_size=2,
                       max_batch_chars=10_000, max_input_chars=3, throttle=Throttle(0),
                       max_retries=1)
    assert len(vecs) == 3
    # 2 appels : lots de 2 puis 1.
    sizes = [len(inputs) for inputs, _ in client.embeddings.calls]
    assert sizes == [2, 1]
    # "cccc" tronqué à 3 → vecteur[0] == 3.
    assert vecs[2][0] == 3.0
    # dim=None ⇒ pas d'output_dimension passé.
    assert all("output_dimension" not in kw for _, kw in client.embeddings.calls)


def test_output_dimension_forwarded() -> None:
    client = _FakeClient()
    embed_texts(client, ["x"], model="m", dim=256, batch_size=8, max_batch_chars=10_000,
                max_input_chars=100, throttle=Throttle(0), max_retries=1)
    assert client.embeddings.calls[0][1]["output_dimension"] == 256


def test_retries_on_rate_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(embed.time, "sleep", lambda *_: None)

    class _Flaky(_FakeEmbeddings):
        def __init__(self) -> None:
            super().__init__()
            self.attempts = 0

        def create(self, model, inputs, **kw):  # noqa: ANN001, ANN003
            self.attempts += 1
            if self.attempts == 1:
                err = RuntimeError("429 Too Many Requests")
                raise err
            return super().create(model, inputs, **kw)

    client = _FakeClient()
    client.embeddings = _Flaky()
    vecs = embed_texts(client, ["a"], model="m", dim=None, batch_size=4,
                       max_batch_chars=10_000, max_input_chars=10, throttle=Throttle(0),
                       max_retries=3)
    assert len(vecs) == 1
    assert client.embeddings.attempts == 2


def test_non_rate_limit_error_propagates(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(embed.time, "sleep", lambda *_: None)

    class _Boom(_FakeEmbeddings):
        def create(self, model, inputs, **kw):  # noqa: ANN001, ANN003
            raise ValueError("schéma invalide")

    client = _FakeClient()
    client.embeddings = _Boom()
    with pytest.raises(ValueError):
        embed_texts(client, ["a"], model="m", dim=None, batch_size=4,
                    max_batch_chars=10_000, max_input_chars=10, throttle=Throttle(0),
                    max_retries=3)
