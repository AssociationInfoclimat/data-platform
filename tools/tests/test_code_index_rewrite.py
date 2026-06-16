"""Tests de la réécriture de requête (code_index.rewrite) avec un chat factice."""
from __future__ import annotations

from code_index.embed import Throttle
from code_index.rewrite import rewrite_query


class _Resp:
    def __init__(self, content: str) -> None:
        self.choices = [type("C", (), {"message": type("M", (), {"content": content})()})()]


class _Chat:
    def __init__(self, content: str) -> None:
        self._content = content
        self.calls: list[dict] = []

    def complete(self, **kw):  # noqa: ANN003
        self.calls.append(kw)
        return _Resp(self._content)


class _Client:
    def __init__(self, content: str) -> None:
        self.chat = _Chat(content)


def test_rewrite_returns_model_output() -> None:
    client = _Client("routing forum handleForumRoute dispatch")
    out = rewrite_query(client, "où est géré le routing des forums ?", model="m",
                        throttle=Throttle(0), max_retries=1)
    assert out == "routing forum handleForumRoute dispatch"
    assert client.chat.calls and "temperature" in client.chat.calls[0]


def test_rewrite_empty_question_passthrough() -> None:
    client = _Client("ignoré")
    assert rewrite_query(client, "   ", model="m", throttle=Throttle(0), max_retries=1) == ""
    assert client.chat.calls == []  # pas d'appel pour une requête vide


def test_rewrite_blank_output_falls_back_to_question() -> None:
    client = _Client("   ")
    q = "décodage HMAC"
    assert rewrite_query(client, q, model="m", throttle=Throttle(0), max_retries=1) == q


def test_rewrite_api_error_falls_back_to_question() -> None:
    class _Boom:
        chat = type("C", (), {"complete": staticmethod(
            lambda **kw: (_ for _ in ()).throw(ValueError("boom")))})()

    q = "anti-scraping auth"
    assert rewrite_query(_Boom(), q, model="m", throttle=Throttle(0), max_retries=1) == q
