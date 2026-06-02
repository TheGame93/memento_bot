#!/usr/bin/env python3
"""Generate docstring indexes for modules, handlers, and mainbot bootstrap symbols.

Walks modules/, extracts public functions and classes via the `ast`
module (no runtime import of the package), and writes compact markdown
indexes to docs/truth/:
  - info_functions.md  — utilities/core modules (non-handlers)
  - info_handlers.md   — modules/handlers/ subtree only
  - info_mainbotfunctions.md — public symbols in mainbot.py

Usage (run from project root):
    python3 scripts/gen_info_functions.py
"""

from __future__ import annotations

import ast
from pathlib import Path

SRC_ROOT = Path("modules")
OUTPUT_UTILS = Path("docs/truth/info_functions.md")
OUTPUT_HANDLERS = Path("docs/truth/info_handlers.md")
OUTPUT_MAINBOT = Path("docs/truth/info_mainbotfunctions.md")
HANDLERS_ROOT = Path("modules/handlers")
MAINBOT_FILE = Path("mainbot.py")


def _module_name(path: Path) -> str:
    """Convert a source file path to a dotted module name."""
    return ".".join(path.with_suffix("").parts)


def _render_args(args: ast.arguments) -> str:
    """Render function arguments as 'name: type, ...' skipping self/cls."""
    parts = []
    for arg in args.posonlyargs + args.args + args.kwonlyargs:
        if arg.arg in ("self", "cls"):
            continue
        if arg.annotation:
            parts.append(f"`{arg.arg}: {ast.unparse(arg.annotation)}`")
        else:
            parts.append(f"`{arg.arg}`")
    if args.vararg:
        a = args.vararg
        ann = f": {ast.unparse(a.annotation)}" if a.annotation else ""
        parts.append(f"`*{a.arg}{ann}`")
    if args.kwarg:
        a = args.kwarg
        ann = f": {ast.unparse(a.annotation)}" if a.annotation else ""
        parts.append(f"`**{a.arg}{ann}`")
    return ", ".join(parts) if parts else "—"


def _render_return(node: ast.FunctionDef | ast.AsyncFunctionDef) -> str:
    """Render the return annotation, or '—' if absent."""
    return f"`{ast.unparse(node.returns)}`" if node.returns else "—"


def _entry(
    name: str,
    parent: str,
    inputs: str,
    output: str,
    description: str,
) -> str:
    """Format one compact markdown entry line."""
    return f"- `{name}` | `{parent}` | {inputs} | {output} | {description}"


def _extract_entries(path: Path) -> list[tuple[int, str]]:
    """Return (lineno, markdown_entry) tuples for public symbols in path."""
    source = path.read_text(encoding="utf-8")
    try:
        tree = ast.parse(source, filename=str(path))
    except SyntaxError:
        return []

    file_rel = str(path).replace("\\", "/")
    mod_name = _module_name(path)
    entries: list[tuple[int, str]] = []

    for node in tree.body:
        # ── Top-level class ──────────────────────────────────────────────
        if isinstance(node, ast.ClassDef):
            if node.name.startswith("_"):
                continue
            doc = ast.get_docstring(node) or "(no docstring)"
            e = _entry(node.name, mod_name, "—", "—", doc.splitlines()[0])
            entries.append((node.lineno, e))

            # Public methods (excluding dunder methods except __init__)
            for item in node.body:
                if not isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    continue
                if item.name.startswith("_"):
                    continue
                mdoc = ast.get_docstring(item) or "(no docstring)"
                e = _entry(
                    item.name,
                    node.name,
                    _render_args(item.args),
                    _render_return(item),
                    mdoc.splitlines()[0],
                )
                entries.append((item.lineno, e))

        # ── Top-level function ────────────────────────────────────────────
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if node.name.startswith("_"):
                continue
            doc = ast.get_docstring(node) or "(no docstring)"
            e = _entry(
                node.name,
                mod_name,
                _render_args(node.args),
                _render_return(node),
                doc.splitlines()[0],
            )
            entries.append((node.lineno, e))

    return entries


def _write_index(entries: list[tuple[str, int, str]], output: Path, title: str, location: str) -> None:
    """Write a sorted markdown index file from (file_rel, lineno, markdown) entries."""
    entries.sort(key=lambda x: (x[0], x[1]))

    header = (
        f"# {title}\n\n"
        f"> **Location:** `{location}`  \n"
        "> **Auto-generated** by `scripts/gen_info_functions.py` — do not edit by hand.  \n"
        "> Re-run whenever public functions are added, renamed, or removed:\n"
        "> `python3 scripts/gen_info_functions.py`\n\n"
        "Fields per entry: `name | parent | inputs | output | description`\n\n"
    )

    lines: list[str] = []
    current_file: str | None = None
    for file_rel, _, text in entries:
        if file_rel != current_file:
            if current_file is not None:
                lines.append("")
            lines.append(f"## `{file_rel}`")
            current_file = file_rel
        lines.append(text)

    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(header + "\n".join(lines) + "\n", encoding="utf-8")
    print(f"Written {len(entries)} entries to {output}")


def main() -> None:
    """Walk project sources and write utility/handler/mainbot docstring indexes."""
    if not SRC_ROOT.exists():
        raise SystemExit(
            f"Source root not found: {SRC_ROOT}\n"
            "Run this script from the project root directory."
        )

    utils_entries: list[tuple[str, int, str]] = []
    handler_entries: list[tuple[str, int, str]] = []
    mainbot_entries: list[tuple[str, int, str]] = []

    for path in sorted(SRC_ROOT.rglob("*.py")):
        file_rel = str(path).replace("\\", "/")
        extracted = [(file_rel, lineno, text) for lineno, text in _extract_entries(path)]
        if path.is_relative_to(HANDLERS_ROOT):
            handler_entries.extend(extracted)
        else:
            utils_entries.extend(extracted)

    _write_index(utils_entries, OUTPUT_UTILS, "Utility and Core Module Index", str(OUTPUT_UTILS))
    _write_index(handler_entries, OUTPUT_HANDLERS, "Handler and Flow Index", str(OUTPUT_HANDLERS))
    if MAINBOT_FILE.exists():
        file_rel = str(MAINBOT_FILE).replace("\\", "/")
        mainbot_entries = [
            (file_rel, lineno, text)
            for lineno, text in _extract_entries(MAINBOT_FILE)
        ]
    _write_index(
        mainbot_entries,
        OUTPUT_MAINBOT,
        "Mainbot Public Symbol Index",
        str(OUTPUT_MAINBOT),
    )


if __name__ == "__main__":
    main()
