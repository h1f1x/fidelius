"""PROTOTYP, wegwerfen: liefert app/fidelius/static von der Platte aus, /api/* geht an die laufende App.

So lassen sich Prototypen im Frontend ansehen, ohne das Image neu zu bauen. Vorher: make up.
Start: python3 scripts/prototype-serve.py, dann http://localhost:8081/?beispiel=A
Die Beispiele kommen direkt aus examples/, damit die Auswahl auch ohne Mount in der App gefüllt ist.
"""
import http.server
import json
import pathlib
import urllib.error
import urllib.parse
import urllib.request

STATIC = pathlib.Path(__file__).resolve().parent.parent / "app" / "fidelius" / "static"
EXAMPLES = pathlib.Path(__file__).resolve().parent.parent / "examples"
UPSTREAM = "http://localhost:8080"
PORT = 8081


class Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *a, **kw):
        super().__init__(*a, directory=str(STATIC), **kw)

    def translate_path(self, path):
        path = path.split("?", 1)[0]
        if path == "/":
            path = "/index.html"
        elif path.startswith("/static/"):
            path = path[len("/static"):]
        return super().translate_path(path)

    def end_headers(self):
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def do_GET(self):
        if self.path.startswith("/api/examples"):
            return self.examples()
        if self.path.startswith("/api/"):
            return self.proxy()
        super().do_GET()

    def do_POST(self):
        self.proxy()

    def examples(self):
        name = self.path[len("/api/examples"):].strip("/")
        if not name:
            out = []
            for p in sorted(EXAMPLES.glob("*.txt")):
                lines = p.read_text(encoding="utf-8").splitlines()
                title = next((l[len("Betreff:"):].strip() for l in lines if l.startswith("Betreff:")), p.stem)
                out.append({"name": p.stem, "title": title})
        else:
            p = EXAMPLES / f"{pathlib.Path(urllib.parse.unquote(name)).name}.txt"
            out = {"name": p.stem, "text": p.read_text(encoding="utf-8")}
        data = json.dumps(out).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def proxy(self):
        body = self.rfile.read(int(self.headers.get("Content-Length") or 0)) or None
        req = urllib.request.Request(UPSTREAM + self.path, data=body, method=self.command,
                                     headers={"Content-Type": self.headers.get("Content-Type", "application/json")})
        try:
            with urllib.request.urlopen(req, timeout=600) as r:
                status, ctype, data = r.status, r.headers.get("Content-Type"), r.read()
        except urllib.error.HTTPError as e:
            status, ctype, data = e.code, e.headers.get("Content-Type"), e.read()
        self.send_response(status)
        self.send_header("Content-Type", ctype or "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


if __name__ == "__main__":
    print(f"Prototyp: http://localhost:{PORT}/?beispiel=A  (API von {UPSTREAM})")
    http.server.ThreadingHTTPServer(("127.0.0.1", PORT), Handler).serve_forever()
