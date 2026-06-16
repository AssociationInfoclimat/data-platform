"""Tests du contexte préfixé (code_index.context) : structurel + LLM par fichier factice."""
from __future__ import annotations

import json

from code_index import context
from code_index.chunk import Chunk
from code_index.context import (apply_context, contexts_for_file, structural_context)
from code_index.embed import Throttle

PHP = (
    "<?php\n"
    "// En-tête du fichier de routing.\n"
    "function handleForumRoute($req) {\n"
    "    $id = $req->get('id');\n"
    "    return render($id);\n"
    "}\n"
)


def test_structural_context_finds_enclosing_symbol() -> None:
    ch = Chunk(start_line=4, end_line=5, text="    $id = $req->get('id');\n")
    ctx = structural_context("site-infoclimat", "forums/index.php", "php", PHP, ch)
    assert "repo site-infoclimat" in ctx
    assert "forums/index.php (php)" in ctx
    assert "handleForumRoute" in ctx
    assert "lignes 4-5/6" in ctx


def test_structural_context_no_symbol() -> None:
    text = "a = 1\nb = 2\n"
    ch = Chunk(start_line=1, end_line=2, text=text)
    ctx = structural_context("repo", "f.txt", "text", text, ch)
    assert "dans" not in ctx  # pas de déclaration trouvée
    assert "lignes 1-2/2" in ctx


def test_apply_context_prefixes_only_when_present() -> None:
    assert apply_context("ctx", "code") == "ctx\n\ncode"
    assert apply_context("", "code") == "code"
    assert apply_context("   ", "code") == "code"


def test_contexts_for_file_off_returns_empty_strings() -> None:
    chunks = [Chunk(1, 2, "x"), Chunk(2, 3, "y")]
    out = contexts_for_file(None, "r", "p", "py", "x\ny\n", chunks, mode="off",
                            model="m", throttle=Throttle(0), max_retries=1, max_file_chars=1000)
    assert out == ["", ""]


def test_contexts_for_file_struct_no_client() -> None:
    chunks = [Chunk(3, 5, "body")]
    out = contexts_for_file(None, "site-infoclimat", "forums/index.php", "php", PHP, chunks,
                            mode="struct", model="m", throttle=Throttle(0), max_retries=1,
                            max_file_chars=1000)
    assert len(out) == 1 and "handleForumRoute" in out[0]


class _Msg:
    def __init__(self, content: str) -> None:
        self.message = type("M", (), {"content": content})()


class _ChatResp:
    def __init__(self, content: str) -> None:
        self.choices = [_Msg(content)]


class _FakeChat:
    def __init__(self, content: str) -> None:
        self._content = content
        self.calls: list[dict] = []

    def complete(self, **kw):  # noqa: ANN003
        self.calls.append(kw)
        return _ChatResp(self._content)


class _FakeClient:
    def __init__(self, content: str) -> None:
        self.chat = _FakeChat(content)


def test_build_file_contexts_llm_parses_json() -> None:
    chunks = [Chunk(1, 2, "a"), Chunk(3, 4, "b")]
    payload = json.dumps({"contexts": [{"i": 0, "context": "rôle A"},
                                       {"i": 1, "context": "rôle B"}]})
    client = _FakeClient(payload)
    out = contexts_for_file(client, "r", "p", "py", "a\nb\nc\nd\n", chunks, mode="llm",
                            model="m", throttle=Throttle(0), max_retries=1, max_file_chars=1000)
    assert out == ["rôle A", "rôle B"]
    # Un seul appel pour tout le fichier (pas un par chunk).
    assert len(client.chat.calls) == 1


def test_build_file_contexts_fills_gaps_with_structural() -> None:
    chunks = [Chunk(1, 2, "a"), Chunk(3, 4, "b")]
    # Le LLM ne couvre que l'indice 0 → l'indice 1 retombe sur le structurel.
    client = _FakeClient(json.dumps({"contexts": [{"i": 0, "context": "rôle A"}]}))
    out = contexts_for_file(client, "repo", "f.py", "python", "a\nb\nc\nd\n", chunks,
                            mode="llm", model="m", throttle=Throttle(0), max_retries=1,
                            max_file_chars=1000)
    assert out[0] == "rôle A"
    assert "lignes 3-4" in out[1]  # contexte structurel de repli


def test_build_file_contexts_invalid_json_falls_back() -> None:
    chunks = [Chunk(1, 2, "a")]
    client = _FakeClient("pas du json")
    out = contexts_for_file(client, "repo", "f.py", "python", "a\nb\n", chunks, mode="llm",
                            model="m", throttle=Throttle(0), max_retries=1, max_file_chars=1000)
    assert len(out) == 1 and "lignes 1-2" in out[0]


def test_build_file_contexts_api_error_falls_back() -> None:
    chunks = [Chunk(1, 1, "a")]

    class _Boom:
        chat = type("C", (), {"complete": staticmethod(
            lambda **kw: (_ for _ in ()).throw(ValueError("boom")))})()

    out = contexts_for_file(_Boom(), "repo", "f.py", "python", "a\n", chunks, mode="llm",
                            model="m", throttle=Throttle(0), max_retries=1, max_file_chars=1000)
    assert len(out) == 1 and "lignes 1-1" in out[0]
