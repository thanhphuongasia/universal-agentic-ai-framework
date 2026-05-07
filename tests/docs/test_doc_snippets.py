"""Validate all Python code snippets in docs/ compile and use valid import paths.

RED criteria:
- Fails if docs/guides/ or docs/cookbook/ don't exist yet.
- Fails if any ```python block has a SyntaxError.
- Fails if any `from uaaf.X import Y` path cannot be resolved.
"""

from __future__ import annotations

import importlib
import re
from pathlib import Path

import pytest

DOCS_ROOT = Path(__file__).parent.parent.parent / "docs"
GUIDES_DIR = DOCS_ROOT / "guides"
COOKBOOK_DIR = DOCS_ROOT / "cookbook"

PYTHON_BLOCK_RE = re.compile(r"```python\n(.*?)```", re.DOTALL)
IMPORT_FROM_RE = re.compile(r"^from (uaaf[\w.]*) import", re.MULTILINE)


def collect_md_files() -> list[Path]:
    files = list(GUIDES_DIR.glob("*.md")) + list(COOKBOOK_DIR.glob("*.md"))
    return sorted(files)


def extract_snippets(md_path: Path) -> list[tuple[str, int]]:
    """Return list of (code, approx_line_number) from python blocks."""
    text = md_path.read_text()
    results = []
    for m in PYTHON_BLOCK_RE.finditer(text):
        code = m.group(1)
        line = text[: m.start()].count("\n") + 1
        results.append((code, line))
    return results


# --- Tests ---


def test_guides_dir_exists():
    assert GUIDES_DIR.exists(), f"Missing {GUIDES_DIR} — create docs/guides/"


def test_cookbook_dir_exists():
    assert COOKBOOK_DIR.exists(), f"Missing {COOKBOOK_DIR} — create docs/cookbook/"


def test_getting_started_exists():
    assert (GUIDES_DIR / "getting-started.md").exists()


def test_migration_guide_exists():
    assert (GUIDES_DIR / "migration.md").exists()


@pytest.mark.parametrize(
    "name",
    [
        "01-todo-app.md",
        "02-flashcard-system.md",
        "03-coding-practice.md",
        "04-stock-trading.md",
    ],
)
def test_cookbook_file_exists(name: str):
    assert (COOKBOOK_DIR / name).exists(), f"Missing docs/cookbook/{name}"


@pytest.mark.parametrize("md_file", collect_md_files(), ids=lambda p: p.name)
def test_python_snippets_compile(md_file: Path):
    for code, line in extract_snippets(md_file):
        try:
            compile(code, str(md_file), "exec")
        except SyntaxError as exc:
            pytest.fail(
                f"SyntaxError in {md_file.name} near doc-line {line}:\n{exc}\n\nCode:\n{code}"
            )


@pytest.mark.parametrize("md_file", collect_md_files(), ids=lambda p: p.name)
def test_uaaf_import_paths_exist(md_file: Path):
    for code, line in extract_snippets(md_file):
        for module_path in IMPORT_FROM_RE.findall(code):
            try:
                importlib.import_module(module_path)
            except ImportError as exc:
                pytest.fail(
                    f"Bad import `{module_path}` in {md_file.name} near doc-line {line}: {exc}"
                )
