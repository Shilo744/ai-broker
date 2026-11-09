"""Maintenance tool for the UI translation (Hebrew source strings, English in aibroker/i18n_en.py).

  python tools/i18n_tool.py list            show every Hebrew string literal and what the tool would do with it
  python tools/i18n_tool.py wrap            wrap the safe ones in T(...)   (run once; the code is under git)
  python tools/i18n_tool.py check           CI-style check: every Hebrew literal is wrapped by T() or whitelisted, and every T() key has an English text

A literal is wrapped when it is evaluated at run time inside a function (a label, a message, a tooltip). It is NOT wrapped when it is a docstring, a module or class
constant (those are translated where they are used), a comparison / dictionary key (they are identifiers), or a regular expression."""
import ast
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TARGETS = ["aibroker/gui.py", "aibroker/kit.py", "aibroker/assistant.py", "aibroker/permissions.py", "aibroker/system.py", "aibroker/daemon.py", "aibroker/mcp_server.py", "aibroker/catalog.py"]
HEB = re.compile("[֐-׿]")
# Files whose module / class constants are wrapped too (the window process fixes its language at start; a change of language restarts the window).
# The other files (permissions, daemon ...) run in the broker process: their constants stay plain and are wrapped where they are USED.
CONST_WRAP = {"aibroker/gui.py", "aibroker/kit.py", "aibroker/assistant.py"}
# Hebrew literals that are internal codes, never shown, and compared elsewhere: never translated.
KEEP = {"בוטל", "(שוב)"}


def parents_of(tree):
    par = {}
    for node in ast.walk(tree):
        for ch in ast.iter_child_nodes(node):
            par[ch] = node
    return par


def classify(node, par):
    """('wrap'|'skip-doc'|'skip-const'|'skip-risky'|'already', why)"""
    p = par.get(node)
    if isinstance(p, ast.Call) and isinstance(p.func, ast.Name) and p.func.id == "T":
        return "already", ""
    if isinstance(p, ast.Expr):
        return "skip-doc", "docstring / bare string"
    if isinstance(p, ast.JoinedStr):
        return "skip-risky", "f-string"
    if isinstance(p, ast.Compare) or (isinstance(p, ast.Subscript) and p.slice is node) or isinstance(p, ast.Dict) and node in p.keys:
        return "skip-risky", "used as a key / compared"
    if isinstance(p, (ast.Tuple, ast.List, ast.Set)) and isinstance(par.get(p), ast.Compare):
        return "skip-risky", "membership test"
    # module / class level?
    n, in_func = node, False
    while n in par:
        n = par[n]
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
            in_func = True
            break
    if not in_func:
        return "skip-const", "module / class constant"
    return "wrap", ""


def scan(path):
    src = (ROOT / path).read_text(encoding="utf-8")
    tree = ast.parse(src)
    par = parents_of(tree)
    out = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str) and HEB.search(node.value):
            kind, why = classify(node, par)
            if node.value in KEEP:
                kind, why = "skip-risky", "internal code"
            elif kind == "skip-const" and path in CONST_WRAP:
                kind, why = "wrap", "constant (window process)"
            elif node.value.startswith("[") and "\u0590" in node.value:
                kind, why = "skip-risky", "regex"
            out.append((node, kind, why))
    out.sort(key=lambda t: (t[0].lineno, t[0].col_offset))
    return src, out


def cmd_list():
    summary = {}
    for t in TARGETS:
        _src, items = scan(t)
        for node, kind, why in items:
            summary[kind] = summary.get(kind, 0) + 1
            if kind != "wrap" and kind != "already":
                print("%-10s %s:%d  %s   %r" % (kind, t, node.lineno, why, node.value[:70]))
    print(summary)


def cmd_wrap():
    for t in TARGETS:
        src, items = scan(t)
        lines = src.split("\n")
        todo = [(n, k) for n, k, _w in items if k == "wrap"]
        if not todo:
            continue
        # replace from the end of the file so that earlier positions stay valid
        for node, _k in sorted(todo, key=lambda x: (x[0].lineno, x[0].col_offset), reverse=True):
            l0, c0, l1, c1 = node.lineno - 1, node.col_offset, node.end_lineno - 1, node.end_col_offset
            # col offsets are in UTF-8 bytes
            def b2c(line, col):
                return len(line.encode("utf-8")[:col].decode("utf-8"))
            c0c, c1c = b2c(lines[l0], c0), b2c(lines[l1], c1)
            lines[l1] = lines[l1][:c1c] + ")" + lines[l1][c1c:]
            lines[l0] = lines[l0][:c0c] + "T(" + lines[l0][c0c:]
        text = "\n".join(lines)
        if "from .i18n import T" not in text and "from aibroker.i18n import T" not in text:
            # add the import after the last top-level import line of the first import block
            m = list(re.finditer(r"^(?:from \. import [^\n]+|from \.[a-z_]+ import [^\n]+)\n", text, re.M))
            if m:
                pos = m[0].start()
                text = text[:pos] + "from .i18n import T\n" + text[pos:]
            else:
                text = re.sub(r"^(import [^\n]+\n)", r"\1from .i18n import T\n", text, count=1, flags=re.M)
        (ROOT / t).write_text(text, encoding="utf-8")
        print("wrapped %d strings in %s" % (len(todo), t))


def cmd_check():
    sys.path.insert(0, str(ROOT))
    from aibroker.i18n_en import EN
    bad = 0
    keys = set()
    for t in TARGETS:
        _src, items = scan(t)
        for node, kind, why in items:
            if kind == "wrap":
                print("UNWRAPPED %s:%d %r" % (t, node.lineno, node.value[:60]))
                bad += 1
        tree = ast.parse((ROOT / t).read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "T" and node.args and isinstance(node.args[0], ast.Constant):
                keys.add(node.args[0].value)
    for t in TARGETS:
        if t in CONST_WRAP:
            continue
        _src, items = scan(t)
        for node, kind, _why in items:
            if kind == "skip-const":
                keys.add(node.value)
    for k in sorted(keys):
        if HEB.search(k) and k not in EN and k not in KEEP:
            print("NO ENGLISH: %r" % k[:80])
            bad += 1
    print("%d Hebrew keys, %d problems" % (len(keys), bad))
    return bad


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    cmd = sys.argv[1] if len(sys.argv) > 1 else "list"
    if cmd == "list":
        cmd_list()
    elif cmd == "wrap":
        cmd_wrap()
    elif cmd == "check":
        sys.exit(1 if cmd_check() else 0)
