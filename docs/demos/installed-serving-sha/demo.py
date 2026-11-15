"""Disposable loopback serving-identity demo; no production service or tracker."""
import hashlib
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import types

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
from shantytown import resume_kinds

BASE = "6c6da5cf96076bfe3e88c01e98a12fb1656735b9"
SHA = "a" * 40
before = types.ModuleType("before")
exec(subprocess.check_output(["git", "-C", str(ROOT), "show", BASE + ":shantytown/resume_kinds.py"], text=True), before.__dict__)
print("target=source checkout + disposable loopback /version fixture")
print("base=" + BASE)
print("candidate_resume_kinds_sha256=" + hashlib.sha256((ROOT / "shantytown/resume_kinds.py").read_bytes()).hexdigest())
print("trigger=installed:quipu@" + SHA)
try:
    before.validate("installed", "quipu@" + SHA)
except ValueError:
    print("BEFORE: REFUSED full serving commit target")
else:
    raise AssertionError("base unexpectedly accepted full commit")

state = {"git_sha": SHA, "git_dirty": False, "version": "0.17.0"}


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        assert self.path == "/version"
        body = json.dumps(state).encode()
        self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


with tempfile.TemporaryDirectory() as directory:
    server = HTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever)
    thread.start()
    saved = {key: os.environ.get(key) for key in ("SHANTY_ROOT", "QUIPU_AUTH_TOKEN")}
    try:
        root = Path(directory)
        (root / "shantytown.toml").write_text(f'[env]\nQUIPU_SERVER = "http://127.0.0.1:{server.server_port}"\n')
        os.environ["SHANTY_ROOT"] = str(root)
        os.environ["QUIPU_AUTH_TOKEN"] = "isolated-demo-only"
        met, _ = resume_kinds.evaluate("installed", "quipu@" + SHA)
        print("AFTER clean exact serving SHA: " + str(met))
        assert met is True
        state["git_sha"] = "b" * 40
        met, _ = resume_kinds.evaluate("installed", "quipu@" + SHA)
        print("CONTROL same version, different serving SHA: " + str(met))
        assert met is False
        state.update(git_sha=SHA, git_dirty=True)
        met, _ = resume_kinds.evaluate("installed", "quipu@" + SHA)
        print("CONTROL dirty serving identity: " + ("UNKNOWN" if met is None else str(met)))
        assert met is None
    finally:
        server.shutdown()
        server.server_close()
        thread.join()
        for key, value in saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
