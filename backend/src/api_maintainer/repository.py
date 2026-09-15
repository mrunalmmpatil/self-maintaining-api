"""Bounded local repository snapshots; never execute client code on the host."""

import ast
import os
import sys
from pathlib import Path

from .contracts import InputError

SKIP = {
    ".git",
    ".hg",
    ".svn",
    ".venv",
    "venv",
    "node_modules",
    "__pycache__",
    ".local-data",
    "dist",
    "build",
    ".next",
    ".pytest_cache",
    ".mypy_cache",
    ".idea",
    ".vscode",
}
EXTENSIONS = {
    ".py",
    ".js",
    ".jsx",
    ".ts",
    ".tsx",
    ".mjs",
    ".cjs",
    ".json",
    ".yaml",
    ".yml",
    ".toml",
    ".md",
    ".txt",
    ".ini",
    ".cfg",
    ".go",
    ".rs",
    ".java",
    ".kt",
    ".cs",
    ".rb",
    ".php",
    ".sh",
    ".xml",
    ".html",
    ".css",
    ".sql",
    ".graphql",
}
CODE = {
    ".py",
    ".js",
    ".jsx",
    ".ts",
    ".tsx",
    ".mjs",
    ".cjs",
    ".go",
    ".rs",
    ".java",
    ".kt",
    ".cs",
    ".rb",
    ".php",
    ".html",
    ".css",
    ".sql",
    ".graphql",
}


def editable(name):
    p = Path(name)
    return (
        p.suffix in CODE
        and not any(x.lower() in {"tests", "test", "__tests__", "fixtures"} for x in p.parts)
        and not (
            p.name.startswith("test_")
            or p.stem.endswith(("_test", ".test", ".spec"))
            or p.name == "conftest.py"
        )
    )


def snapshot_files(location):
    root = Path(location).expanduser()
    if not root.is_absolute() or not root.is_dir():
        raise InputError("Client repository must be an existing absolute local directory path.")
    files = {}
    size = 0
    for directory, dirs, names in os.walk(root, followlinks=False):
        dirs[:] = sorted(
            d
            for d in dirs
            if d not in SKIP and not d.startswith(".") and not (Path(directory) / d).is_symlink()
        )
        for name in sorted(names):
            p = Path(directory) / name
            if p.is_symlink() or name.startswith(".") or p.suffix.lower() not in EXTENSIONS:
                continue
            if any(word in name.lower() for word in ("secret", "credential", "private_key")):
                continue
            if p.stat().st_size > 1024 * 1024:
                raise InputError("A repository text file exceeds 1 MiB. Use a smaller client directory.")
            raw = p.read_bytes()
            try:
                raw.decode("utf-8")
            except UnicodeError:
                continue
            if b"\x00" in raw:
                continue
            size += len(raw)
            if size > 10 * 1024 * 1024 or len(files) >= 1000:
                raise InputError(
                    "Repository snapshot exceeds 1,000 files or 10 MiB. Select a smaller client directory."
                )
            files[str(p.relative_to(root))] = raw
    if not any(editable(name) for name in files):
        raise InputError("No supported client source files found in this directory.")
    return files


STDLIB_TEST_COMMAND = ["python", "-m", "unittest", "discover"]


def _imports(source):
    """Top-level module names a Python source file imports, or None if it does not parse."""
    try:
        tree = ast.parse(source)
    except (SyntaxError, ValueError):
        return None
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name.partition(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and not node.level and node.module:
            names.add(node.module.partition(".")[0])
    return names


def infer_test_command(files):
    """Suggest a standard-library test command, or nothing when the repository needs more.

    The default check image carries only the standard library, so guessing for a
    repository that imports anything else would surface a missing dependency as a
    failed migration. A command is offered only when the snapshot holds unittest-style
    tests and every import resolves to the standard library or to the snapshot itself.
    """
    sources = {name: raw for name, raw in files.items() if name.endswith(".py")}
    local = {Path(name).stem for name in sources}
    local |= {Path(name).parts[0] for name in files if len(Path(name).parts) > 1}
    tests = False
    for name, raw in sources.items():
        stem = Path(name).stem
        tests = tests or stem.startswith("test_") or stem.endswith("_test")
        imported = _imports(raw.decode("utf-8", "replace"))
        if imported is None or imported - sys.stdlib_module_names - local:
            return []
    return list(STDLIB_TEST_COMMAND) if tests else []
