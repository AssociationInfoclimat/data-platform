"""Tests de découverte de fichiers (code_index.walk) — sans réseau ni dépendance lourde."""
from __future__ import annotations

from pathlib import Path

from code_index.walk import is_excluded, iter_files

MANIFEST = {
    "repos": ["repoA", "repoB"],
    "include_ext": [".php", ".py", ".map", ".js"],
    "exclude_dirs": [".git", "vendor", "node_modules"],
    "exclude_globs": ["*.min.js", "*.js.map", "*.lock"],
}


def _touch(path: Path, content: bytes = b"x = 1\n") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)


def test_is_excluded_dir_and_globs() -> None:
    dirs, globs = {".git", "vendor"}, ["*.min.js", "*.js.map"]
    assert is_excluded("vendor/lib/x.php", dirs, globs)
    assert is_excluded(".git/config", dirs, globs)
    assert is_excluded("web/app.min.js", dirs, globs)
    assert is_excluded("web/app.js.map", dirs, globs)
    assert not is_excluded("forums/index.php", dirs, globs)


def test_iter_files_filters(tmp_path: Path) -> None:
    base = tmp_path
    _touch(base / "repoA" / "forums" / "index.php")
    _touch(base / "repoA" / "assets" / "app.min.js")        # exclu (glob)
    _touch(base / "repoA" / "assets" / "app.js.map")        # exclu (source-map)
    _touch(base / "repoA" / "vendor" / "dep" / "z.php")     # exclu (dir)
    _touch(base / "repoA" / ".git" / "config")              # exclu (dir)
    _touch(base / "repoA" / "logo.png", b"\x89PNG\x00")     # exclu (extension)
    _touch(base / "repoA" / "mapserver" / "isobares.map")   # GARDÉ (mapfile)
    _touch(base / "repoA" / "bin" / "blob.py", b"a\x00b")   # exclu (binaire)
    _touch(base / "repoB" / "tool.py")

    found = list(iter_files(MANIFEST, base))
    keys = {f.key for f in found}

    assert "repoA/forums/index.php" in keys
    assert "repoA/mapserver/isobares.map" in keys
    assert "repoB/tool.py" in keys
    assert "repoA/assets/app.min.js" not in keys
    assert "repoA/assets/app.js.map" not in keys
    assert "repoA/vendor/dep/z.php" not in keys
    assert "repoA/.git/config" not in keys
    assert "repoA/logo.png" not in keys
    assert "repoA/bin/blob.py" not in keys


def test_iter_files_repo_filter_and_lang(tmp_path: Path) -> None:
    _touch(tmp_path / "repoA" / "a.php")
    _touch(tmp_path / "repoB" / "b.py")
    only_a = list(iter_files(MANIFEST, tmp_path, repos=["repoA"]))
    assert [f.key for f in only_a] == ["repoA/a.php"]
    assert only_a[0].lang == "php"


def test_max_file_bytes(tmp_path: Path) -> None:
    _touch(tmp_path / "repoA" / "big.py", b"#" * 5000)
    found = list(iter_files(MANIFEST, tmp_path, repos=["repoA"], max_file_bytes=1000))
    assert found == []
