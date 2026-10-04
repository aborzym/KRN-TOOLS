from __future__ import annotations

import secrets
import shutil
import subprocess
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread
from urllib.parse import urlencode


class ChromePreview:
    def __init__(self, path: Path) -> None:
        self.path = path.expanduser().resolve()
        route = f"/{secrets.token_urlsafe(24)}/score.krn"
        source_path = self.path

        class Handler(BaseHTTPRequestHandler):
            def _cors_headers(self) -> None:
                origin = self.headers.get("Origin")
                if origin in (
                    "http://verovio.humdrum.org",
                    "https://verovio.humdrum.org",
                ):
                    self.send_header("Access-Control-Allow-Origin", origin)
                    self.send_header("Vary", "Origin")
                self.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")
                self.send_header("Access-Control-Allow-Headers", "*")
                self.send_header("Access-Control-Allow-Private-Network", "true")

            def do_OPTIONS(self) -> None:
                if self.path != route:
                    self.send_error(404)
                    return
                self.send_response(204)
                self._cors_headers()
                self.end_headers()

            def do_GET(self) -> None:
                if self.path != route:
                    self.send_error(404)
                    return

                try:
                    data = source_path.read_bytes()
                except OSError:
                    self.send_response(404)
                    self._cors_headers()
                    self.end_headers()
                    return

                self.send_response(200)
                self._cors_headers()
                self.send_header("Content-Type", "text/plain; charset=utf-8")
                self.send_header("Cache-Control", "no-store")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                try:
                    self.wfile.write(data)
                except (BrokenPipeError, ConnectionResetError):
                    pass

            def log_message(self, *_args) -> None:
                pass

        self._server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self._server.daemon_threads = True
        self._thread = Thread(
            target=self._server.serve_forever,
            kwargs={"poll_interval": 0.1},
            daemon=True,
        )
        self._thread.start()

        file_url = f"http://127.0.0.1:{self._server.server_port}{route}"
        self.url = "http://verovio.humdrum.org/?" + urlencode({"k": "e", "file": file_url})

    def open(self) -> None:
        if sys.platform == "darwin":
            command = ["/usr/bin/open", "-a", "Google Chrome", self.url]
        elif sys.platform.startswith("linux"):
            executable = next(
                (
                    found
                    for name in ("google-chrome", "google-chrome-stable")
                    if (found := shutil.which(name))
                ),
                None,
            )
            if executable is None:
                raise OSError("Nie znaleziono Google Chrome.")
            command = [executable, self.url]
        else:
            raise OSError("Podgląd Chrome obsługuje obecnie macOS i Linux.")

        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        if result.returncode:
            raise OSError(result.stderr.strip() or "Nie można otworzyć Chrome.")

    def close(self) -> None:
        self._server.shutdown()
        self._server.server_close()
        self._thread.join(timeout=1)
