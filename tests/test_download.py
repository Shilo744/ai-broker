"""Tests of the download runner against a LOCAL http server (nothing leaves the machine):  python tests/test_download.py
resume after a cut connection, checksum check, refusing other hosts, an existing good file is left alone."""
import hashlib
import http.server
import os
import socketserver
import sys
import tempfile
import threading

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "runners"))
import download_file as dl

DATA = os.urandom(3 * 1024 * 1024 + 123)
SHA = hashlib.sha256(DATA).hexdigest()
state = {"cut_once": True, "ranges": []}


class H(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_GET(self):
        if self.path == "/missing.bin":
            self.send_error(404)
            return
        rng = self.headers.get("Range")
        start = 0
        if rng and rng.startswith("bytes="):
            start = int(rng[6:].split("-")[0])
            state["ranges"].append(start)
        body = DATA[start:]
        self.send_response(206 if start else 200)
        self.send_header("Content-Length", str(len(body)))
        if start:
            self.send_header("Content-Range", "bytes %d-%d/%d" % (start, len(DATA) - 1, len(DATA)))
        self.end_headers()
        if self.path == "/cut.bin" and state["cut_once"] and not start:
            state["cut_once"] = False
            self.wfile.write(body[: 1024 * 1024])               # the connection drops after 1 MB
            self.wfile.flush()
            self.connection.close()
            return
        self.wfile.write(body)


def run():
    bad = 0

    def check(name, cond, extra=""):
        nonlocal bad
        print(("PASS " if cond else "FAIL ") + name + (("  |  " + str(extra)) if extra else ""))
        bad += not cond

    srv = socketserver.ThreadingTCPServer(("127.0.0.1", 0), H)
    srv.daemon_threads = True
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = "http://127.0.0.1:%d" % srv.server_address[1]
    tmp = tempfile.mkdtemp(prefix="aibroker_dl_")
    d1 = os.path.join(tmp, "a", "model.bin")
    check("plain download with checksum", dl.main(["--url", base + "/ok.bin", "--dest", d1, "--sha256", SHA, "--size", str(len(DATA))]) == 0 and open(d1, "rb").read() == DATA)
    check("no .part file is left", not os.path.exists(d1 + ".part"))
    check("a finished matching file is left alone", dl.main(["--url", base + "/ok.bin", "--dest", d1, "--sha256", SHA]) == 0)
    d2 = os.path.join(tmp, "b", "cut.bin")
    rc = dl.main(["--url", base + "/cut.bin", "--dest", d2, "--sha256", SHA])
    check("a cut connection resumes with a Range request", rc == 0 and open(d2, "rb").read() == DATA and state["ranges"] and state["ranges"][0] > 0, state["ranges"])
    d3 = os.path.join(tmp, "c", "bad.bin")
    check("a wrong checksum is refused and nothing is kept", dl.main(["--url", base + "/ok.bin", "--dest", d3, "--sha256", "0" * 64]) == 3 and not os.path.exists(d3) and not os.path.exists(d3 + ".part"))
    check("a wrong size is refused", dl.main(["--url", base + "/ok.bin", "--dest", d3, "--size", "5"]) == 3 and not os.path.exists(d3))
    check("another host is refused", dl.main(["--url", "https://evil.example.com/x.bin", "--dest", d3]) == 2)
    check("plain http to a non-local host is refused", dl.main(["--url", "http://huggingface.co/x.bin", "--dest", d3]) == 2)
    check("a missing file (404) is refused, not retried forever", dl.main(["--url", base + "/missing.bin", "--dest", d3]) == 2)
    print("download test: %d failed" % bad)
    return bad


if __name__ == "__main__":
    sys.exit(1 if run() else 0)
