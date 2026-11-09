"""Safe file download for the broker's `download` job type (model weights, tools).

  download_file.py --url https://huggingface.co/<repo>/resolve/main/<file> --dest <path> [--sha256 HEX] [--size BYTES]

Only https from known hosts (checked again after redirects), resumes an interrupted download (<dest>.part), verifies size and SHA-256 before the file gets its
final name, never overwrites a finished file that already matches, prints one progress line a second (PROGRESS <percent> <done> <total> <MB/s>).
Exit codes: 0 ok (or already there), 2 refused (bad URL, host not allowed, not enough disk), 3 size / checksum mismatch, 4 network failure after retries.
Plain http is accepted only for 127.0.0.1 / localhost (the tests run a local server)."""
import argparse
import hashlib
import os
import shutil
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

ALLOWED = ("huggingface.co", "hf.co", "githubusercontent.com", "github.com", "download.blender.org", "godotengine.org", "pypi.org", "files.pythonhosted.org")
LOCAL = ("127.0.0.1", "localhost")
CHUNK = 1 << 20
RETRIES = 5


def host_ok(url, extra):
    p = urllib.parse.urlparse(url)
    host = (p.hostname or "").lower()
    if p.scheme == "http" and host in LOCAL:
        return True
    if p.scheme != "https" or not host:
        return False
    return any(host == a or host.endswith("." + a) for a in tuple(ALLOWED) + tuple(x.lower() for x in extra))


def sha256_of(path, upto=None):
    h = hashlib.sha256()
    left = upto
    with open(path, "rb") as f:
        while True:
            n = CHUNK if left is None else min(CHUNK, left)
            if n <= 0:
                break
            b = f.read(n)
            if not b:
                break
            h.update(b)
            if left is not None:
                left -= len(b)
    return h


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", required=True)
    ap.add_argument("--dest", required=True)
    ap.add_argument("--sha256", default="")
    ap.add_argument("--size", type=int, default=0)
    ap.add_argument("--allow-host", action="append", default=[])
    a = ap.parse_args(argv)
    want_hash = a.sha256.strip().lower()
    if not host_ok(a.url, a.allow_host):
        print("REFUSED: %s is not an allowed source (https from a known host only)" % urllib.parse.urlparse(a.url).hostname)
        return 2
    dest = os.path.abspath(a.dest)
    part = dest + ".part"
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    if os.path.exists(dest):
        ok = (not a.size or os.path.getsize(dest) == a.size) and (not want_hash or sha256_of(dest).hexdigest() == want_hash)
        if ok:
            print("ALREADY OK: %s" % dest)
            return 0
        print("an existing file does not match; downloading again")
    t0 = time.time()
    attempt = 0
    while True:
        attempt += 1
        have = os.path.getsize(part) if os.path.exists(part) else 0
        req = urllib.request.Request(a.url, headers={"User-Agent": "ai-broker-download/1.0"})
        if have:
            req.add_header("Range", "bytes=%d-" % have)
        try:
            with urllib.request.urlopen(req, timeout=40) as r:
                if not host_ok(r.geturl(), a.allow_host + ["cdn-lfs.huggingface.co", "cas-bridge.xethub.hf.co", "xethub.hf.co"]):
                    print("REFUSED: the download was redirected to a host that is not allowed: %s" % urllib.parse.urlparse(r.geturl()).hostname)
                    return 2
                if have and r.status != 206:
                    have = 0                                                    # the server ignored Range: start again
                total = a.size or ((int(r.headers.get("Content-Length", 0)) + have) if r.headers.get("Content-Length") else 0)
                if total:
                    free = shutil.disk_usage(os.path.dirname(dest)).free
                    if free < (total - have) + (1 << 30):
                        print("REFUSED: not enough free disk space (%.1f GB free, %.1f GB needed)" % (free / 1e9, (total - have) / 1e9))
                        return 2
                h = hashlib.sha256()
                if have:
                    h = sha256_of(part, have)
                mode = "ab" if have else "wb"
                done, last, last_done = have, time.time(), have
                with open(part, mode) as f:
                    while True:
                        b = r.read(CHUNK)
                        if not b:
                            break
                        f.write(b)
                        h.update(b)
                        done += len(b)
                        now = time.time()
                        if now - last >= 1.0:
                            rate = (done - last_done) / (now - last) / 1e6
                            print("PROGRESS %.1f %d %d %.1f" % (100.0 * done / total if total else 0.0, done, total, rate), flush=True)
                            last, last_done = now, done
                if total and done < total:                  # http.client does not raise when the server closes early: check it ourselves, then resume
                    raise OSError("the connection closed early (%d of %d bytes)" % (done, total))
            break
        except (urllib.error.URLError, OSError, TimeoutError) as e:
            if isinstance(e, urllib.error.HTTPError) and e.code in (401, 403, 404):
                print("REFUSED by the server (HTTP %d): the file is not available without an account or does not exist" % e.code)
                return 2
            if attempt >= RETRIES:
                print("NETWORK FAILURE after %d tries: %s" % (attempt, e))
                return 4
            print("network problem (%s); retry %d of %d in %d s, the download resumes" % (e, attempt, RETRIES, 2 * attempt), flush=True)
            time.sleep(2 * attempt)
    size_now = os.path.getsize(part)
    if a.size and size_now != a.size:
        os.remove(part)
        print("SIZE MISMATCH: got %d bytes, expected %d" % (size_now, a.size))
        return 3
    if want_hash and h.hexdigest() != want_hash:
        os.remove(part)
        print("CHECKSUM MISMATCH: got %s, expected %s" % (h.hexdigest(), want_hash))
        return 3
    os.replace(part, dest)
    print("PROGRESS 100.0 %d %d 0.0" % (size_now, size_now))
    print("DONE %s (%.1f MB in %.0f s, sha256 %s)" % (dest, size_now / 1e6, time.time() - t0, h.hexdigest()))
    return 0


if __name__ == "__main__":
    sys.exit(main())
