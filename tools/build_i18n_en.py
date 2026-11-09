"""One-off: joins the indexed English texts (en_texts_a.py, en_texts_b.py) with the frozen Hebrew key list (shots/keys_all.json) into aibroker/i18n_en.py.
After this ran, i18n_en.py is edited directly (Hebrew key -> English text)."""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
from en_texts_a import A
from en_texts_b import B

keys = json.loads((ROOT / "shots" / "keys_all.json").read_text(encoding="utf-8"))
texts = dict(A)
texts.update(B)
texts[48] = "held by the broker"
texts[49] = "held by another program"
texts[184] = "Out"
texts[71] = "Cancelled"
skip = {15, 16, 29}
missing = [i for i in range(len(keys)) if i not in texts and i not in skip]
print("keys", len(keys), "translated", len(texts), "missing", missing)
lines = ['"""English texts of the UI. Key = the Hebrew source string used in the code (T("...")), value = the English text with the same %s / %d placeholders in the same order."""', "", "EN = {"]
for i in sorted(texts):
    lines.append("    %r: %r," % (keys[i], texts[i]))
lines.append("}")
lines.append("")
lines.append("# a word that means two things in Hebrew: T(word, context) looks here first")
lines.append("EN_CTX = {")
lines.append("    (\"btn\", \"עצור\"): \"Stop\",")
lines.append("}")
(ROOT / "aibroker" / "i18n_en.py").write_text("\n".join(lines) + "\n", encoding="utf-8")
print("written", len(texts))
