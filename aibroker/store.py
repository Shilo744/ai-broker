"""SQLite job store + job-type loading + learned estimates."""
import json
import re
import sqlite3
import threading
import time

from . import paths

COLS = ["id", "type", "name", "requester", "state", "pos", "manual", "held", "params", "cmd", "cwd", "env", "model", "klass", "est_key",
        "est_ram", "est_vram", "est_commit", "est_source", "max_parallel", "hold_lock", "self_lock", "after_id", "timeout_s",
        "submitted", "started", "finished", "rc", "pid", "peak_ws", "peak_commit", "peak_vram", "avail_before", "log", "note", "outdir"]
JSON_COLS = ("params", "cmd", "env")

SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
  id INTEGER PRIMARY KEY AUTOINCREMENT, type TEXT, name TEXT, requester TEXT, state TEXT, pos REAL, manual INT DEFAULT 0, held INT DEFAULT 0,
  params TEXT, cmd TEXT, cwd TEXT, env TEXT, model TEXT, klass TEXT, est_key TEXT,
  est_ram REAL, est_vram REAL, est_commit REAL, est_source TEXT, max_parallel INT, hold_lock INT, self_lock INT, after_id INT, timeout_s INT,
  submitted REAL, started REAL, finished REAL, rc INT, pid INT, peak_ws REAL, peak_commit REAL, peak_vram REAL, avail_before REAL, log TEXT, note TEXT);
CREATE INDEX IF NOT EXISTS jobs_state ON jobs(state);
"""


class Store:
    def __init__(self, path=None):
        paths.HOME.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(str(path or paths.DB), check_same_thread=False, isolation_level=None)
        self.db.row_factory = sqlite3.Row
        self.db.executescript(SCHEMA)
        try:
            self.db.execute("ALTER TABLE jobs ADD COLUMN outdir TEXT")
        except sqlite3.OperationalError:
            pass
        self.lock = threading.RLock()

    @staticmethod
    def _row(r):
        d = dict(r)
        for c in JSON_COLS:
            try:
                d[c] = json.loads(d[c]) if d[c] else ({} if c != "cmd" else [])
            except ValueError:
                d[c] = {}
        return d

    def add(self, job):
        with self.lock:
            cols = [c for c in COLS if c != "id" and c in job]
            vals = [json.dumps(job[c]) if c in JSON_COLS else job[c] for c in cols]
            cur = self.db.execute("INSERT INTO jobs(%s) VALUES(%s)" % (",".join(cols), ",".join("?" * len(cols))), vals)
            return cur.lastrowid

    def get(self, jid):
        with self.lock:
            r = self.db.execute("SELECT * FROM jobs WHERE id=?", (jid,)).fetchone()
            return self._row(r) if r else None

    def update(self, jid, **kw):
        with self.lock:
            cols = list(kw)
            vals = [json.dumps(kw[c]) if c in JSON_COLS else kw[c] for c in cols]
            self.db.execute("UPDATE jobs SET %s WHERE id=?" % ",".join(c + "=?" for c in cols), vals + [jid])

    def by_state(self, *states):
        with self.lock:
            q = "SELECT * FROM jobs WHERE state IN (%s) ORDER BY pos, id" % ",".join("?" * len(states))
            return [self._row(r) for r in self.db.execute(q, states).fetchall()]

    def finished(self, limit=200):
        with self.lock:
            q = "SELECT * FROM jobs WHERE state IN ('done','failed','cancelled','lost') ORDER BY finished DESC, id DESC LIMIT ?"
            return [self._row(r) for r in self.db.execute(q, (limit,)).fetchall()]

    def durations(self, est_key, n=10):
        """Seconds the last n successful runs of the same est_key took (newest first): the base of the 'about N seconds left' estimate."""
        with self.lock:
            q = "SELECT finished-started FROM jobs WHERE est_key=? AND state='done' AND started>0 AND finished>started ORDER BY id DESC LIMIT ?"
            return [r[0] for r in self.db.execute(q, (est_key, n)).fetchall()]

    def type_stats(self):
        """{type: {n, median_s, ram, vram}} over the successful runs (the 'what it costs on this machine' line of the model pages)."""
        import statistics
        out = {}
        with self.lock:
            rows = self.db.execute("SELECT type, finished-started, peak_ws, peak_vram FROM jobs WHERE state='done' AND started>0 AND finished>started ORDER BY id DESC").fetchall()
        by = {}
        for t, d, ram, vr in rows:
            by.setdefault(t, []).append((d, ram or 0, vr or 0))
        for t, v in by.items():
            v = v[:15]
            out[t] = {"n": len(v), "median_s": statistics.median(x[0] for x in v), "ram": max(x[1] for x in v), "vram": max(x[2] for x in v)}
        return out

    def next_pos(self):
        with self.lock:
            r = self.db.execute("SELECT MAX(pos) FROM jobs WHERE state='queued'").fetchone()
            return (r[0] or 0) + 1.0

    def renumber(self, ids):
        with self.lock:
            for i, jid in enumerate(ids, 1):
                self.db.execute("UPDATE jobs SET pos=? WHERE id=?", (float(i), jid))

    def history(self, est_key, n=10):
        """Peaks of the last n successful runs of the same est_key (newest first)."""
        with self.lock:
            q = "SELECT peak_ws, peak_commit, peak_vram FROM jobs WHERE est_key=? AND state='done' AND peak_ws>0 ORDER BY id DESC LIMIT ?"
            return [dict(r) for r in self.db.execute(q, (est_key, n)).fetchall()]

    def prune(self, keep):
        with self.lock:
            self.db.execute("DELETE FROM jobs WHERE state IN ('done','failed','cancelled','lost') AND id NOT IN "
                            "(SELECT id FROM jobs WHERE state IN ('done','failed','cancelled','lost') ORDER BY id DESC LIMIT ?)", (keep,))


def _p90(vals):
    vals = sorted(vals)
    return vals[min(len(vals) - 1, int(round(0.9 * (len(vals) - 1))))]


def learned_estimate(store, est_key, default):
    """Estimate = 1.1 x 90th percentile of the last 10 successful runs; falls back to the type default."""
    h = store.history(est_key)
    if not h:
        return dict(default, source="default (not measured yet)")
    ram = _p90([x["peak_ws"] for x in h]) * 1.1
    com = _p90([x["peak_commit"] or 0 for x in h]) * 1.1
    vr = _p90([x["peak_vram"] or 0 for x in h]) * 1.1
    return {"ram_gb": round(max(ram, 0.3), 2), "commit_gb": round(max(com, ram), 2),
            "vram_gb": round(vr if vr > 0.05 else default.get("vram_gb", 0.0), 2),
            "source": "learned from %d run%s" % (len(h), "" if len(h) == 1 else "s")}


# ---------------------------------------------------------------- job types
def load_types():
    types = {}
    dirs = [paths.TYPES_DIR] + sorted(paths.ADAPTERS.glob("*/jobtypes")) + [paths.USER_TYPES_DIR]
    for d in dirs:
        if d.is_dir():
            for f in sorted(d.glob("*.json")):
                try:
                    t = json.loads(f.read_text(encoding="utf-8"))
                    types[t["id"]] = t
                except (OSError, ValueError, KeyError):
                    pass
    return types


class _Fmt(dict):
    def __missing__(self, k):
        raise KeyError(k)


def render(value, ctx):
    """Replace {name} placeholders in a string (leaves the string alone when it has none)."""
    return re.sub(r"\{(\w+)\}", lambda m: str(ctx[m.group(1)]) if m.group(1) in ctx else m.group(0), value)


def resolve_command(t, params, cfgvars, extra=None):
    """Merge defaults and user params, check required ones, expand the cmd template. A '{*extra}' element expands to params['extra'] (list).
    An element whose placeholder has no value (optional parameter) is dropped together with a preceding '--flag' element."""
    spec = t.get("params", {})
    full = {}
    base = dict(cfgvars)
    base.update(extra or {})                       # e.g. {outdir}: the job's own output folder
    for k, v in spec.items():
        d = v.get("default") if isinstance(v, dict) else v
        if isinstance(d, str):
            d = render(d, base)
        req = isinstance(v, dict) and v.get("required")
        if k in params and params[k] not in (None, ""):
            full[k] = params[k]
        elif d is not None:
            full[k] = d
        elif req:
            raise ValueError("missing parameter '%s' for type %s" % (k, t["id"]))
    for k, v in params.items():
        full.setdefault(k, v)

    def _r(v):                                      # {outdir} (and path variables) may also appear in values the requester passes
        if isinstance(v, str):
            return render(v, base)
        if isinstance(v, list):
            return [_r(x) for x in v]
        return v
    full = {k: _r(v) for k, v in full.items()}
    ctx = dict(base)
    ctx.update({k: v for k, v in full.items()})
    cmd = []
    for part in t["cmd"]:
        m = re.fullmatch(r"\{\*(\w+)\}", part)
        if m:                                                   # {*name}: splice the list parameter 'name' (nothing when absent)
            v = full.get(m.group(1)) or []
            cmd.extend(str(x) for x in (v if isinstance(v, list) else [v]))
            continue
        if any(m not in ctx for m in re.findall(r"\{(\w+)\}", part)):
            if cmd and cmd[-1].startswith("--") and "{" not in cmd[-1]:
                cmd.pop()
            continue
        cmd.append(render(part, ctx))
    env = {k: render(str(v), ctx) for k, v in (t.get("env") or {}).items()}
    est_key = render(t.get("est_key", t["id"]), ctx)
    return full, cmd, env, est_key


def now():
    return time.time()
