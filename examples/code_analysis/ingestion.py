"""
Phase: Ingestion
================
Parse Python source files → extract classes with methods, docstrings, complexity.
Uses stdlib `ast` only — no external dependencies.
"""

from __future__ import annotations

import ast
import textwrap
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class MethodInfo:
    name: str
    args: list[str]
    docstring: str
    line_count: int
    is_async: bool = False
    is_property: bool = False

    def summary(self) -> str:
        kind = "async " if self.is_async else ""
        prop = "@property " if self.is_property else ""
        return f"{prop}{kind}def {self.name}({', '.join(self.args)}) [{self.line_count}L]"


@dataclass
class ClassInfo:
    name: str
    file_path: str
    module: str
    line_start: int
    line_end: int
    docstring: str
    base_classes: list[str]
    methods: list[MethodInfo] = field(default_factory=list)

    @property
    def line_count(self) -> int:
        return self.line_end - self.line_start + 1

    @property
    def complexity_score(self) -> int:
        """Rough complexity: lines + method count * 2 + base classes * 3."""
        return self.line_count + len(self.methods) * 2 + len(self.base_classes) * 3

    @property
    def public_methods(self) -> list[MethodInfo]:
        return [m for m in self.methods if not m.name.startswith("_")]

    @property
    def private_methods(self) -> list[MethodInfo]:
        return [m for m in self.methods if m.name.startswith("_") and not m.name.startswith("__")]

    @property
    def dunder_methods(self) -> list[MethodInfo]:
        return [m for m in self.methods if m.name.startswith("__")]

    def summary(self) -> str:
        bases = f"({', '.join(self.base_classes)})" if self.base_classes else ""
        return (
            f"class {self.name}{bases} | {self.line_count}L | "
            f"{len(self.methods)} methods | complexity={self.complexity_score}"
        )

    def to_context_text(self) -> str:
        """Serialise to text for GraphBackbone ingestion."""
        lines = [
            f"CLASS: {self.name}",
            f"Module: {self.module}",
            f"File: {self.file_path}",
            f"Lines: {self.line_start}-{self.line_end} ({self.line_count} total)",
            f"Bases: {', '.join(self.base_classes) or 'object'}",
            f"Complexity score: {self.complexity_score}",
        ]
        if self.docstring:
            lines.append(f"Docstring: {textwrap.shorten(self.docstring, width=200)}")
        lines.append(f"Methods ({len(self.methods)}):")
        for m in self.methods:
            lines.append(f"  - {m.summary()}")
        return "\n".join(lines)


class PythonIngester:
    """Parse Python files and extract ClassInfo objects using ast."""

    def ingest_file(self, path: Path) -> list[ClassInfo]:
        source = path.read_text(encoding="utf-8", errors="replace")
        try:
            tree = ast.parse(source, filename=str(path))
        except SyntaxError:
            return []

        module_name = path.stem
        lines = source.splitlines()
        classes: list[ClassInfo] = []

        for node in ast.walk(tree):
            if not isinstance(node, ast.ClassDef):
                continue

            docstring = ast.get_docstring(node) or ""
            end_line = self._end_line(node, len(lines))

            bases = [
                (b.id if isinstance(b, ast.Name) else getattr(b, "attr", str(b)))
                for b in node.bases
            ]

            methods: list[MethodInfo] = []
            for item in node.body:
                if not isinstance(item, ast.FunctionDef | ast.AsyncFunctionDef):
                    continue
                m_doc = ast.get_docstring(item) or ""
                m_args = [a.arg for a in item.args.args if a.arg != "self"]
                m_end = self._end_line(item, len(lines))
                m_lines = m_end - item.lineno + 1
                is_prop = any(
                    (d.id if isinstance(d, ast.Name) else getattr(d, "attr", "")) == "property"
                    for d in item.decorator_list
                )
                methods.append(MethodInfo(
                    name=item.name,
                    args=m_args,
                    docstring=m_doc,
                    line_count=m_lines,
                    is_async=isinstance(item, ast.AsyncFunctionDef),
                    is_property=is_prop,
                ))

            classes.append(ClassInfo(
                name=node.name,
                file_path=str(path),
                module=module_name,
                line_start=node.lineno,
                line_end=end_line,
                docstring=docstring,
                base_classes=bases,
                methods=methods,
            ))
        return classes

    def ingest_directory(self, directory: Path, max_files: int = 50) -> list[ClassInfo]:
        all_classes: list[ClassInfo] = []
        py_files = sorted(directory.rglob("*.py"))[:max_files]
        for py_file in py_files:
            if "__pycache__" in str(py_file):
                continue
            all_classes.extend(self.ingest_file(py_file))
        return all_classes

    @staticmethod
    def _end_line(node: ast.AST, total_lines: int) -> int:
        """Get the last line of an AST node."""
        if hasattr(node, "end_lineno") and node.end_lineno:
            return node.end_lineno  # type: ignore[no-any-return]
        return total_lines
