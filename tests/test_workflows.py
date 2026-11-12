"""Saved workflows (aibroker/workflows.py): validation, {variable} and {step.outdir} filling, chaining with `after`, stopping at a step that cannot be queued.
Needs no service and no GPU:  python tests/test_workflows.py"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tests"))
import sandbox                                   # noqa: E402,F401  (first: a throw-away data folder)
from aibroker import workflows                   # noqa: E402

bad = 0


def check(name, cond, extra=""):
    global bad
    bad += not cond
    print(("PASS " if cond else "FAIL ") + name + (("  |  " + str(extra)[:300]) if extra and not cond else ""), flush=True)


WF = {"name": "car_to_3d", "title": "Car", "vars": {"prompt": "a red car", "size": 1024},
      "steps": [{"id": "img", "type": "zimage", "params": {"prompt": "{prompt}", "size": "{size}"}},
                {"id": "shape", "type": "triposg_shape", "params": {"image": "{img.outdir}/out.png", "list": ["{img.outdir}/a", "x"]}},
                {"id": "run", "type": "custom", "command": ["python", "go.py", "{shape.outdir}"], "est_ram_gb": 1}]}
TYPES = {"zimage", "triposg_shape", "custom"}

check("a good workflow has no problems", workflows.validate(WF, TYPES) == [], workflows.validate(WF, TYPES))
check("unknown job type is reported", any("unknown job type" in p for p in workflows.validate(dict(WF, steps=[{"id": "a", "type": "nope"}]), TYPES)))
check("a reference to a LATER step is reported", any("does not come before" in p for p in workflows.validate(
    dict(WF, steps=[{"id": "a", "type": "zimage", "params": {"p": "{b.outdir}"}}, {"id": "b", "type": "zimage"}]), TYPES)))
check("an unknown variable is reported", any("not a workflow variable" in p for p in workflows.validate(
    dict(WF, vars={}, steps=[{"id": "a", "type": "zimage", "params": {"p": "{prompt}"}}]), TYPES)))
check("duplicate step ids are reported", any("duplicate" in p for p in workflows.validate(dict(WF, steps=[{"id": "a", "type": "zimage"}, {"id": "a", "type": "zimage"}]), TYPES)))
check("a bad name is reported", workflows.validate(dict(WF, name="../x"), TYPES) != [])
check("a custom step needs a command", any("command" in p for p in workflows.validate(dict(WF, steps=[{"id": "a", "type": "custom"}]), TYPES)))

r = workflows.save(WF, TYPES)
check("save writes the file and load reads it back", r["ok"] and workflows.load("car_to_3d")["title"] == "Car", r)
check("save refuses a bad workflow", not workflows.save(dict(WF, name="x y"), TYPES)["ok"])
check("listing shows it with its step ids and variables", workflows.listing()[0]["steps"] == ["img", "shape", "run"] and workflows.listing()[0]["vars"]["size"] == 1024)
check("a name with a path in it is not loaded", workflows.load("../x") is None)

calls = []


def submit(req):
    calls.append(req)
    n = len(calls)
    return {"ok": True, "id": 100 + n, "outdir": r"C:\out\job%d" % n}


res = workflows.run(workflows.load("car_to_3d"), {"prompt": "a blue boat"}, submit)
check("run queues every step", res["ok"] and [j["job_id"] for j in res["jobs"]] == [101, 102, 103], res)
check("each step waits for the one before (after)", [c["after"] for c in calls] == [None, 101, 102], [c["after"] for c in calls])
check("a given value beats the default, a default fills the rest", calls[0]["params"] == {"prompt": "a blue boat", "size": "1024"}, calls[0]["params"])
check("{step.outdir} is filled, also inside lists, with forward slashes", calls[1]["params"] == {"image": "C:/out/job1/out.png", "list": ["C:/out/job1/a", "x"]}, calls[1]["params"])
check("a custom command is filled too and keeps its memory estimate", calls[2]["command"] == ["python", "go.py", "C:/out/job2"] and calls[2]["est_ram_gb"] == 1, calls[2])

calls.clear()


def failing(req):
    calls.append(req)
    return {"ok": True, "id": 7, "outdir": r"C:\o"} if len(calls) == 1 else {"ok": False, "error": "no such type"}


res = workflows.run(workflows.load("car_to_3d"), None, failing)
check("a step that cannot be queued stops the run and says which", (not res["ok"]) and res["failed_step"] == "shape" and res["queued"][0]["job_id"] == 7, res)

print("workflow test: %d failed" % bad)
sys.exit(1 if bad else 0)
