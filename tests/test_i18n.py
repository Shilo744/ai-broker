"""Checks of the UI translation (no window):  python tests/test_i18n.py
1. every Hebrew string literal in the code is wrapped in T() (or is a documented internal code), and every T() key has an English text;
2. an English text has the same %s / %d placeholders as its Hebrew source, in the same order;
3. every job type has English title, group and description."""
import glob
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools"))
import i18n_tool
from aibroker.i18n_en import EN

SPEC = re.compile(r"%(?!%)[-+ #0]*\d*(?:\.\d+)?[sdfi]")


def run():
    bad = 0
    if i18n_tool.cmd_check():
        bad += 1
    for he, en in EN.items():
        a, b = SPEC.findall(he), SPEC.findall(en)
        if a != b:
            print("PLACEHOLDERS differ: %r -> %r" % (he[:50], en[:50]))
            bad += 1
    for f in sorted(glob.glob(os.path.join(ROOT, "jobtypes", "*.json")) + glob.glob(os.path.join(ROOT, "adapters", "*", "jobtypes", "*.json"))):
        d = json.load(open(f, encoding="utf-8"))
        for k in ("en_title", "en_group", "en_desc"):
            if not d.get(k):
                print("job type %s has no %s" % (d.get("id"), k))
                bad += 1
        if d.get("he_about") and not d.get("en_about"):
            print("job type %s has he_about but no en_about" % d.get("id"))
            bad += 1
    print("i18n test: %d problems" % bad)
    return bad


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.exit(1 if run() else 0)
