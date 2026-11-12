"""Transcript helpers that need no model and no GPU: merging the tiny false 'speakers' a noisy recording produces, writing the transcript files, renaming speakers.
  python tests/test_transcribe.py"""
import json
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from aibroker import transcript_fmt as fmt       # noqa: E402

bad = 0


def check(name, cond, extra=""):
    global bad
    bad += not cond
    print(("PASS " if cond else "FAIL ") + name + (("  |  " + str(extra)[:300]) if extra and not cond else ""), flush=True)


path = os.path.join(ROOT, "runners", "transcribe.py")
ns = {"__file__": path}
exec(compile(open(path, encoding="utf-8").read().replace("sys.exit(main())", ""), path, "exec"), ns)          # the runner's own functions, without running it
merge = ns["merge_small"]

turns = [(0, 50, 1), (50, 52, 5), (52, 100, 2), (100, 101, 7), (101, 150, 1)]
got = merge(turns)
check("a voice with under 5 percent of the speech is merged into the nearest main voice", [t[2] for t in got] == [1, 1, 2, 2, 1], got)
check("times are kept when merging", [(t[0], t[1]) for t in got] == [(t[0], t[1]) for t in turns])
check("when everyone is a main voice nothing changes", merge([(0, 10, 1), (10, 20, 2)]) == [(0, 10, 1), (10, 20, 2)])
check("no speech at all is fine", merge([]) == [])
check("speaker_of picks the voice with most overlap", ns["speaker_of"]([(0, 3, 1), (3, 10, 2)], 2, 8) == 2 and ns["speaker_of"]([], 0, 1) is None)

data = {"language": "he", "duration": 9, "names": {}, "segments": [{"start": 0, "end": 2, "text": "שלום", "speaker": 1}, {"start": 2, "end": 3, "text": "מה נשמע", "speaker": 1},
                                                                      {"start": 65, "end": 70, "text": "טוב", "speaker": 2}, {"start": 71, "end": 72, "text": "בלי דובר", "speaker": None}]}
txt, srt = fmt.render(data)
check("one paragraph per speaker turn, with the time and the default Hebrew label", "[00:00] דובר 1: שלום מה נשמע" in txt and "[01:05] דובר 2: טוב" in txt, txt)
check("a sentence without a speaker has no label", "[01:11] בלי דובר" in txt, txt)
check("srt has numbered cues with times", srt.startswith("1\n00:00:00,000 --> 00:00:02,000\nדובר 1: שלום"), srt[:80])
d = tempfile.mkdtemp()
fmt.write(d, data)
fmt.rename(d, {"1": "דנה", "2": "  "})
t2 = open(os.path.join(d, "transcript.txt"), encoding="utf-8").read()
check("renaming a speaker changes txt and srt; an empty name keeps the default", "דנה: שלום מה נשמע" in t2 and "דובר 2: טוב" in t2 and "דנה: שלום" in open(os.path.join(d, "transcript.srt"), encoding="utf-8").read(), t2)
check("the names are kept in the json", json.load(open(os.path.join(d, "transcript.json"), encoding="utf-8"))["names"] == {"1": "דנה"})
data["language"] = "en"
check("English transcripts say Speaker N", "Speaker 1: " in fmt.render(data)[0])
print("transcribe test: %d failed" % bad)
sys.exit(1 if bad else 0)
