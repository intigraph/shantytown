"""Compare actual HTTP reads on two source checkouts using a local fixture."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer


def child(checkout, label):
    sys.path.insert(0, str(Path(checkout).resolve()))
    from shantytown import crew_rules
    crew_rules.request_headers = lambda: {}
    os.environ["NO_PROXY"] = os.environ["no_proxy"] = "127.0.0.1,localhost"
    body = json.dumps({"rows": [], "count": 0, "truncated": False}).encode()
    for case, delay, budget in [("ordinary", 0, 2), ("slow-progress", .01, .2),
                                ("stalled", 0, .2)]:
        received = threading.Event()
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_POST(self):
                self.rfile.read(int(self.headers["Content-Length"]))
                received.set()
                if case == "stalled":
                    time.sleep(.5)
                self.send_response(200)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                try:
                    for byte in body:
                        self.wfile.write(bytes([byte]))
                        self.wfile.flush()
                        if delay:
                            time.sleep(delay)
                except OSError:
                    pass

        server = HTTPServer(("127.0.0.1", 0), Handler)
        server.timeout = .5
        thread = threading.Thread(target=server.handle_request)
        thread.start()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "shantytown.toml").write_text(
                '[env]\nQUIPU_SERVER="http://127.0.0.1:' + str(server.server_port) + '"\n')
            started = time.monotonic()
            try:
                result = crew_rules.ask(root, "fixture", {}, timeout=budget)
                outcome = "accepted"
                assert result == []
            except Exception as error:
                outcome = type(error).__name__
            elapsed = time.monotonic() - started
        thread.join(2)
        server.server_close()
        assert not thread.is_alive()
        assert received.is_set()
        print(json.dumps({"source": label, "case": case, "budget_s": budget,
                          "elapsed_s": round(elapsed, 6), "outcome": outcome}), flush=True)
        if case == "ordinary":
            assert outcome == "accepted"
        elif case == "stalled":
            assert outcome in {"TimeoutError", "URLError"} and elapsed < budget + .45
        elif label == "before":
            assert outcome == "accepted" and elapsed > budget
        else:
            assert outcome == "TimeoutError" and elapsed < budget + .45


if __name__ == "__main__":
    if len(sys.argv) == 4 and sys.argv[1] == "--child":
        child(sys.argv[2], sys.argv[3])
    else:
        if len(sys.argv) != 2:
            raise SystemExit("usage: deadline_demo.py BEFORE_CHECKOUT")
        for label, checkout in [("before", Path(sys.argv[1])),
                                ("after", Path(__file__).resolve().parents[3])]:
            subprocess.run([sys.executable, __file__, "--child", str(checkout), label],
                           check=True)
