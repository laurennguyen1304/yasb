"""Patch installed third-party dependencies so YASB runs on Python 3.12.

YASB (and its ``qt-css-engine`` dependency) target Python 3.14, whose PEP 649
makes annotations lazy and whose PEP 758 allows unparenthesized ``except A, B:``.
On 3.12 those show up as ``NameError`` (forward-ref annotations evaluated
eagerly) and ``SyntaxError`` (multi-type ``except``). YASB's own ``src`` tree is
fixed in this fork; ``qt-css-engine`` is an external package installed into the
virtualenv, so it has to be patched in place after every install/upgrade.

Run this once after ``pip install -e .`` (idempotent — safe to re-run):

    .venv\\Scripts\\python scripts\\patch_py312_deps.py

It:
  1. parenthesizes PEP 758 ``except A, B:`` -> ``except (A, B):``
  2. inserts ``from __future__ import annotations`` (PEP 563) so forward-ref
     annotations are not evaluated eagerly.
"""

from __future__ import annotations

import io
import re
import sys
import tokenize

# except[*] <two or more comma-separated names> :   (no `as`, per PEP 758)
_EXCEPT = re.compile(
    r"^(?P<indent>\s*)except(?P<star>\*?)\s+"
    r"(?P<exc>[A-Za-z_][\w.]*(?:\s*,\s*[A-Za-z_][\w.]*)+)"
    r"(?P<tail>\s*:.*)$"
)


def _parenthesize_excepts(text: str) -> tuple[str, int]:
    out: list[str] = []
    n = 0
    for line in text.splitlines(keepends=True):
        body = line.rstrip("\r\n")
        m = _EXCEPT.match(body)
        if m and " as " not in body:
            nl = line[len(body):]
            exc = ", ".join(p.strip() for p in m.group("exc").split(","))
            line = f"{m.group('indent')}except{m.group('star')} ({exc}){m.group('tail')}{nl}"
            n += 1
        out.append(line)
    return "".join(out), n


def _future_insert_index(text: str) -> int:
    lines = text.splitlines(keepends=True)
    i = 0
    if i < len(lines) and lines[i].startswith("#!"):
        i += 1
    if i < len(lines) and lines[i].lstrip().startswith("#") and "coding" in lines[i]:
        i += 1
    while i < len(lines) and (not lines[i].strip() or lines[i].lstrip().startswith("#")):
        i += 1
    if i < len(lines) and lines[i].lstrip().startswith(('"""', "'''", 'r"""', "r'''")):
        try:
            for tok in tokenize.generate_tokens(io.StringIO(text).readline):
                if tok.type == tokenize.STRING and tok.start[0] - 1 <= i:
                    i = tok.end[0]
                    break
        except Exception:
            pass
    return i


def _add_future(text: str) -> tuple[str, bool]:
    if "from __future__ import annotations" in text:
        return text, False
    lines = text.splitlines(keepends=True)
    idx = _future_insert_index(text)
    stmt = "from __future__ import annotations\n"
    if idx < len(lines) and lines[idx].strip():
        stmt += "\n"
    lines.insert(idx, stmt)
    return "".join(lines), True


def _iter_py_files(pkg_dir: str):
    import os

    for root, _dirs, files in os.walk(pkg_dir):
        for f in files:
            if f.endswith(".py"):
                yield os.path.join(root, f)


def main() -> int:
    try:
        import qt_css_engine
    except ImportError:
        print("qt_css_engine is not installed in this interpreter; nothing to patch.")
        return 0

    import os

    pkg_dir = os.path.dirname(qt_css_engine.__file__)
    changed_files = 0
    except_edits = 0
    for path in _iter_py_files(pkg_dir):
        with open(path, encoding="utf-8") as fh:
            original = fh.read()
        text, n = _parenthesize_excepts(original)
        text, added = _add_future(text)
        if n or added:
            with open(path, "w", encoding="utf-8", newline="") as fh:
                fh.write(text)
            changed_files += 1
            except_edits += n

    print(
        f"Patched qt-css-engine at {pkg_dir}\n"
        f"  files changed: {changed_files}\n"
        f"  except-clauses parenthesized: {except_edits}\n"
        f"  future-annotations import ensured on all modules"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
