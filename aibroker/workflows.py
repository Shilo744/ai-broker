"""Saved workflows: a named list of steps (each step is one broker job) that run one after another, the next starting only when the one before it succeeded.
A workflow is a small JSON file in <home>/workflows/<name>.json:
  {"name": "...", "title": "...", "description": "...", "vars": {"prompt": "a red car"},
   "steps": [{"id": "img", "type": "zimage", "params": {"prompt": "{prompt}"}, "name": "image"},
             {"id": "shape", "type": "triposg_shape", "params": {"image": "{img.outdir}/out.png"}}]}
In a step's params, `{var}` is replaced by a workflow variable (given at run time, else its default in "vars"), and `{<step id>.outdir}` by the output folder of an EARLIER step
(known as soon as that step is queued, so a later step can name a file the earlier one writes there). Nothing here talks to the queue: `run` gets a `submit` function."""
import json
import re

from . import paths

NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,47}$")
TOKEN_RE = re.compile(r"\{([A-Za-z0-9_]+)(?:\.([A-Za-z0-9_]+))?\}")


def folder():
    d = paths.HOME / "workflows"
    d.mkdir(parents=True, exist_ok=True)
    return d


def validate(wf, known_types=None):
    """Returns a list of problems (empty = fine)."""
    bad = []
    if not NAME_RE.match(str(wf.get("name", ""))):
        bad.append("name must be 1-48 letters, digits, - or _ (ASCII), starting with a letter or digit")
    steps = wf.get("steps")
    if not isinstance(steps, list) or not steps:
        return bad + ["steps must be a non-empty list"]
    seen = []
    for i, s in enumerate(steps, 1):
        sid = str(s.get("id", ""))
        if not re.match(r"^[A-Za-z0-9_]+$", sid):
            bad.append("step %d: id must be letters, digits or _" % i)
        elif sid in seen:
            bad.append("step %d: duplicate id %r" % (i, sid))
        if not s.get("type"):
            bad.append("step %d: type is missing" % i)
        elif known_types is not None and s["type"] not in known_types:
            bad.append("step %d: unknown job type %r" % (i, s["type"]))
        if s.get("type") == "custom":
            if not isinstance(s.get("command"), list) or not s.get("command"):
                bad.append("step %d: a custom step needs command=[...]" % i)
        for tok in TOKEN_RE.findall(json.dumps(s.get("params") or {}) + json.dumps(s.get("command") or [])):
            ref, attr = tok
            if attr:
                if ref not in seen:
                    bad.append("step %d: {%s.%s} refers to a step that does not come before it" % (i, ref, attr))
                elif attr != "outdir":
                    bad.append("step %d: only {step.outdir} is available, not .%s" % (i, attr))
            elif ref not in (wf.get("vars") or {}):
                bad.append("step %d: {%s} is not a workflow variable (add it to vars with a default)" % (i, ref))
        seen.append(sid)
    return bad


def save(wf, known_types=None):
    bad = validate(wf, known_types)
    if bad:
        return {"ok": False, "problems": bad}
    p = folder() / ("%s.json" % wf["name"])
    p.write_text(json.dumps(wf, ensure_ascii=False, indent=1), encoding="utf-8")
    return {"ok": True, "path": str(p)}


def load(name):
    if not NAME_RE.match(str(name)):
        return None
    try:
        return json.loads((folder() / ("%s.json" % name)).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def listing():
    out = []
    for p in sorted(folder().glob("*.json")):
        try:
            w = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        out.append({"name": w.get("name", p.stem), "title": w.get("title", ""), "description": w.get("description", ""),
                    "steps": [s.get("id") for s in w.get("steps", [])], "vars": w.get("vars") or {}})
    return out


def _fill(value, scope):
    """Replace {tokens} in strings anywhere inside value (nested lists and dicts)."""
    if isinstance(value, str):
        return TOKEN_RE.sub(lambda m: str(scope.get((m.group(1), m.group(2)), m.group(0))), value)
    if isinstance(value, list):
        return [_fill(v, scope) for v in value]
    if isinstance(value, dict):
        return {k: _fill(v, scope) for k, v in value.items()}
    return value


def run(wf, values, submit):
    """Queue every step in order. submit(req) -> {"ok": True, "id": int, "outdir": str} or {"ok": False, "error": str}; req has type, params, name, command, after.
    If a step cannot be queued the earlier ones stay queued (they are real jobs); the result says which step failed."""
    vars_ = dict(wf.get("vars") or {})
    vars_.update(values or {})
    scope = {(k, None): v for k, v in vars_.items()}
    jobs, prev = [], None
    for s in wf["steps"]:
        req = {"type": s["type"], "params": _fill(s.get("params") or {}, scope), "name": s.get("name") or "%s: %s" % (wf["name"], s["id"]), "after": prev}
        if s.get("command"):
            req["command"] = _fill(s["command"], scope)
        for k in ("est_ram_gb", "est_vram_gb", "timeout_s"):
            if s.get(k) is not None:
                req[k] = s[k]
        r = submit(req)
        if not r.get("ok"):
            return {"ok": False, "failed_step": s["id"], "error": r.get("error"), "queued": jobs}
        jobs.append({"step": s["id"], "job_id": r["id"], "outdir": r.get("outdir", "")})
        scope[(s["id"], "outdir")] = (r.get("outdir") or "").replace("\\", "/")
        prev = r["id"]
    return {"ok": True, "jobs": jobs}
