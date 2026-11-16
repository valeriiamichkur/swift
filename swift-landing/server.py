#!/usr/bin/env python3
"""Local server for the SWIFT landing page.

Usage:
    python3 server.py            # http://localhost:8000
    python3 server.py --port 5050
    python3 server.py --open     # also opens the browser

Only the Python standard library is used.
"""
from __future__ import annotations

import argparse
import functools
import http.server
import socketserver
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parent

# Optional font files (NAMU, Buvera) that the CSS looks for but that may
# not be present yet — don't spam the log with their 404s.
OPTIONAL = ("/assets/fonts/NAMU-", "/assets/fonts/Buvera-")


class Handler(http.server.SimpleHTTPRequestHandler):
    extensions_map = {
        **http.server.SimpleHTTPRequestHandler.extensions_map,
        ".js": "text/javascript",
        ".css": "text/css",
        ".svg": "image/svg+xml",
        ".woff2": "font/woff2",
        ".ttf": "font/ttf",
        ".otf": "font/otf",
    }

    def end_headers(self) -> None:
        # Always serve fresh files while developing.
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def log_request(self, code="-", size="-") -> None:
        if str(code) == "404" and self.path.startswith(OPTIONAL):
            return
        super().log_request(code, size)


def main() -> None:
    parser = argparse.ArgumentParser(description="Serve the SWIFT landing page.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--open", action="store_true", help="open the page in a browser")
    args = parser.parse_args()

    handler = functools.partial(Handler, directory=str(ROOT))
    socketserver.TCPServer.allow_reuse_address = True
    with socketserver.ThreadingTCPServer((args.host, args.port), handler) as httpd:
        url = f"http://{'localhost' if args.host in ('127.0.0.1', '0.0.0.0') else args.host}:{args.port}/"
        print(f"SWIFT landing → {url}   (map page: {url}map.html)\nCtrl+C to stop.")
        if args.open:
            webbrowser.open(url)
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\nStopped.")


if __name__ == "__main__":
    main()
