#!/usr/bin/env python3
# /// script
# requires-python = ">=3.12"
# dependencies = ["httpx>=0.27"]
# ///
"""Lasttest gegen fidelius, Spec: docs/specs/lasttest.md, Abschnitte 1, 2 und 5.

Aufruf über make, Optionen in ARGS:
    make loadtest                                   # Dev-VM über SSH-Tunnel, liest die VM mit
    make loadtest ARGS="--label 16gb"               # Label im Namen des Ergebnisverzeichnisses
    make loadtest ARGS="--url https://… --vm --stages 4 --no-longtext --label caddy"
                                                    # über Caddy bei der Ziellast, eine Stufe,
                                                    # die VM trotzdem mitlesen
    make loadtest ARGS="--url http://localhost:8080 --stages 1,2 --min-duration 20 --min-requests 3"
                                                    # Rauchlauf gegen make up

Treppe gleichzeitiger Prüfungen ohne Denkpause. Jede Stufe läuft, bis mindestens --min-requests
gezählte Prüfungen fertig und --min-duration Sekunden um sind; die erste Prüfung je Nutzer wärmt
auf und zählt nicht. Danach laufen die offenen Anfragen leer. Nach der ersten Stufe mit einer
Bruchbedingung ist Schluss. Zum Ende wiederholt das Skript die Stufe c*, wobei einer der Nutzer
statt der Beispiele den Langtext schickt.

Ohne --url öffnet das Skript einen SSH-Tunnel zur App auf der VM und liest die VM mit. Es nutzt
dieselben Variablen wie make deploy und make remote-login: DEPLOY_HOST (Pflicht), DEPLOY_JUMP,
DEPLOY_BIND (sonst APP_BIND aus der .env auf der VM) und DEPLOY_DIR (Standard fidelius). Mit --url
gibt es keinen Tunnel; die VM liest es dann nur mit --vm mit.

Auf der VM liest das Skript nur: nproc, /proc/meminfo, die .env, docker inspect vor dem Lauf und
nach jeder Stufe, alle 2 s docker stats, /proc/stat und MemAvailable. Es startet und ändert dort
nichts.

Auf dem Mac hält caffeinate den Rechner während des Laufs wach, unter Linux systemd-inhibit. Schläft
er doch ein (Deckel zu), stehen Uhr und Anfragen still, und die Stufe misst Unsinn.

Ergebnis unter loadtest-results/<JJJJ-MM-TT-HHMM>-<vcpu>cpu-<threads>t[-<label>]/ (ohne VM:
…-ohne-vm[-<label>]) mit requests.jsonl, samples.jsonl und run.json. Das Format beschreibt
scripts/loadtest_eval.py, das auch die Auswertung rechnet.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import random
import re
import shlex
import shutil
import socket
import subprocess
import sys
import threading
import time
from collections.abc import Callable
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import httpx
import loadtest_eval as ev

ROOT = Path(__file__).resolve().parent.parent
EXAMPLES = ROOT / "examples"
RESULTS = ROOT / "loadtest-results"

LADDER = (1, 2, 4, 6, 8, 10, 12, 16, 20)
MIN_REQUESTS = 30
MIN_STAGE_S = 180
# Liegt über den 120 s, die die App auf Laya wartet: So zeigt sich, was die App selbst tut.
CLIENT_TIMEOUT_S = 180
CALIBRATION_WAIT_S = 300
# Pause nach einer fehlgeschlagenen Anfrage. Ist die App weg, kommt der Verbindungsfehler sofort
# zurück; ohne Pause schickte jeder Nutzer bis zum Ende der Stufe Tausende Anfragen ins Leere.
FAILED_PAUSE_S = 1
HEADERS = {"X-Fidelius-Quelle": ev.LOAD_TEST_SOURCE}


# ---------- Texte ----------

def load_examples() -> list[tuple[str, str]]:
    return [(p.stem, p.read_text(encoding="utf-8")) for p in sorted(EXAMPLES.glob("*.txt"))]


def long_text(examples: list[tuple[str, str]]) -> str:
    """Alle Beispiele aneinander, derselbe Text wie in der Kalibrierung (calibration.py)."""
    return "\n\n".join(text for _, text in examples)


def user_order(examples: list[tuple[str, str]], user: int) -> list[tuple[str, str]]:
    """Feste Reihenfolge je Nutzer: Jeder Lauf macht auf jeder Größe dieselbe Arbeit."""
    order = list(examples)
    random.Random(user).shuffle(order)
    return order


# ---------- Ausgaben der VM lesen (reine Funktionen) ----------

def sections(text: str) -> dict[str, str]:
    """Teilt eine Ausgabe an Zeilen der Form "@@ name" in benannte Abschnitte."""
    result: dict[str, list[str]] = {}
    current = None
    for line in text.splitlines():
        if line.startswith("@@ "):
            current = line[3:].strip()
            result[current] = []
        elif current is not None:
            result[current].append(line)
    return {name: "\n".join(lines) for name, lines in result.items()}


def env_value(env_text: str, key: str) -> str | None:
    """Wert einer Variable aus einer Compose-.env; die letzte Zuweisung gilt, Anführungszeichen
    fallen weg. None, wenn sie fehlt oder leer ist."""
    value = None
    for line in env_text.splitlines():
        line = line.strip()
        if line.startswith("export "):
            line = line[len("export "):].lstrip()
        if line.startswith(f"{key}="):
            value = line[len(key) + 1:].strip()
            if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
                value = value[1:-1]
    return value or None


def threads_from_env(env_text: str) -> tuple[int, str]:
    """OMP_NUM_THREADS aus der .env, sonst 4 wie in compose.yaml."""
    value = env_value(env_text, "OMP_NUM_THREADS")
    if value and value.isdigit():
        return int(value), ".env"
    return 4, "standard"


def tunnel_target(deploy_bind: str | None, env_text: str) -> tuple[str, int]:
    """Wohin der Tunnel auf der VM zeigt: DEPLOY_BIND, sonst APP_BIND aus der .env, sonst
    127.0.0.1 wie in compose.yaml. Lauscht die App auf 0.0.0.0, geht der Tunnel auf 127.0.0.1."""
    host = deploy_bind or env_value(env_text, "APP_BIND") or "127.0.0.1"
    if host == "0.0.0.0":
        host = "127.0.0.1"
    port = env_value(env_text, "APP_PORT")
    return host, int(port) if port and port.isdigit() else 8080


def meminfo_bytes(text: str) -> dict[str, int]:
    """/proc/meminfo in Bytes, z. B. {"MemTotal": 8130000896, …}."""
    result = {}
    for line in text.splitlines():
        m = re.match(r"^(\w+):\s+(\d+)\s*kB", line)
        if m:
            result[m.group(1)] = int(m.group(2)) * 1024
    return result


def inspect_summary(text: str) -> dict[str, dict]:
    """docker inspect (JSON-Array) → je Compose-Dienst die Felder, die für Brüche zählen."""
    try:
        containers = json.loads(text or "[]")
    except ValueError:
        return {}
    result = {}
    for c in containers if isinstance(containers, list) else []:
        service = (c.get("Config", {}).get("Labels") or {}).get("com.docker.compose.service")
        if not service:
            continue
        env = dict(e.split("=", 1) for e in c.get("Config", {}).get("Env") or [] if "=" in e)
        state = c.get("State", {})
        result[service] = {
            "id": c.get("Id"), "status": state.get("Status"),
            "restart_count": c.get("RestartCount", 0), "oom_killed": bool(state.get("OOMKilled")),
            "started_at": state.get("StartedAt"), "omp_num_threads": env.get("OMP_NUM_THREADS"),
        }
    return result


CPU_FIELDS = ("user", "nice", "system", "idle", "iowait", "irq", "softirq", "steal")


def cpu_counters(line: str) -> dict[str, int] | None:
    """Erste Zeile von /proc/stat ("cpu  user nice system idle iowait irq softirq steal …")."""
    parts = line.split()
    if len(parts) < 1 + len(CPU_FIELDS) or parts[0] != "cpu":
        return None
    return dict(zip(CPU_FIELDS, map(int, parts[1:1 + len(CPU_FIELDS)])))


def cpu_shares(previous: dict | None, current: dict | None) -> dict[str, float] | None:
    """Anteile der CPU-Zeit in % zwischen zwei Ständen von /proc/stat, steal eingeschlossen."""
    if not previous or not current:
        return None
    delta = {k: current[k] - previous[k] for k in CPU_FIELDS}
    total = sum(delta.values())
    if total <= 0:
        return None
    return {k: round(v / total * 100, 1) for k, v in delta.items()}


UNITS = {"B": 1, "kB": 10 ** 3, "KB": 10 ** 3, "MB": 10 ** 6, "GB": 10 ** 9, "TB": 10 ** 12,
         "KiB": 2 ** 10, "MiB": 2 ** 20, "GiB": 2 ** 30, "TiB": 2 ** 40}


def size_bytes(text: str) -> int | None:
    """"3.175GiB" → Bytes, wie docker stats Größen schreibt."""
    m = re.match(r"^\s*([\d.]+)\s*([A-Za-z]+)\s*$", text or "")
    if not m or m.group(2) not in UNITS:
        return None
    return round(float(m.group(1)) * UNITS[m.group(2)])


def container_stats(lines: list[str], ids: dict[str, str]) -> dict[str, dict]:
    """Zeilen von docker stats --format '{{json .}}' → je Dienst CPU in % (bezogen auf eine CPU)
    und belegter RAM. ids: Dienst → volle Container-ID."""
    result = {}
    for line in lines:
        try:
            row = json.loads(line)
        except ValueError:
            continue
        short = row.get("ID") or ""
        service = next((s for s, full in ids.items() if short and
                        (full.startswith(short) or row.get("Container") == full)), None)
        if service is None:
            continue
        cpu = (row.get("CPUPerc") or "").rstrip("%")
        result[service] = {
            "cpu_pct": float(cpu) if re.fullmatch(r"[\d.]+", cpu) else None,
            "mem_bytes": size_bytes((row.get("MemUsage") or "").split("/")[0]),
        }
    return result


def parse_sample(zeit: str, lines: list[str], previous_cpu: dict | None,
                 ids: dict[str, str]) -> tuple[dict, dict | None]:
    """Ein Block des Samplers → (Zeile für samples.jsonl, CPU-Zähler für den nächsten Block)."""
    cpu = next((c for line in lines if (c := cpu_counters(line))), None)
    mem = meminfo_bytes("\n".join(line for line in lines if line.startswith("Mem")))
    sample = {
        "zeit": zeit,
        "container": container_stats([line for line in lines if line.startswith("{")], ids),
        "cpu_pct": cpu_shares(previous_cpu, cpu),
        "mem_total_bytes": mem.get("MemTotal"),
        "mem_available_bytes": mem.get("MemAvailable"),
    }
    return sample, cpu or previous_cpu


def result_dir_name(started: datetime, vcpu: int | None, threads: int | None,
                    label: str | None) -> str:
    size = f"{vcpu}cpu-{threads}t" if vcpu is not None and threads is not None else "ohne-vm"
    name = f"{started:%Y-%m-%d-%H%M}-{size}"
    if label:
        name += "-" + re.sub(r"[^A-Za-z0-9_.-]+", "-", label).strip("-")
    return name


# ---------- VM über ssh ----------

FACTS_SCRIPT = f"""cd {{dir}} || exit 1
echo '@@ nproc'; nproc
echo '@@ meminfo'; cat /proc/meminfo
echo '@@ env'; cat .env 2>/dev/null
echo '@@ inspect'; ids=$(docker compose ps -q {" ".join(ev.CONTAINERS)} </dev/null)
[ -n "$ids" ] && docker inspect $ids </dev/null
"""

# sleep im Hintergrund und wait am Ende: Ein Durchgang dauert 2 s oder, wenn docker stats
# länger braucht, so lange wie docker stats.
SAMPLER_SCRIPT = """while :; do
  sleep 2 &
  echo '@@'
  head -n1 /proc/stat
  grep -E '^(MemTotal|MemAvailable):' /proc/meminfo
  docker stats --no-stream --format '{{json .}}' IDS </dev/null
  wait
done
"""


@dataclass(frozen=True)
class VM:
    """Lesender Zugang zur VM über ssh: host ist das Ziel (etwa user@vm), jump der Sprung-Host
    oder None, directory das Verzeichnis von Compose. Die Skripte gehen wie bei deploy.sh über
    stdin an bash, so braucht es keine zweite Ebene Quoting für die Remote-Shell."""
    host: str
    jump: str | None
    directory: str

    @classmethod
    def from_env(cls) -> VM:
        host = os.environ.get("DEPLOY_HOST")
        if not host:
            sys.exit("DEPLOY_HOST fehlt, siehe docs/deployen.md (oder --url ohne --vm).")
        return cls(host, os.environ.get("DEPLOY_JUMP") or None,
                   os.environ.get("DEPLOY_DIR") or "fidelius")

    def ssh(self, *options: str) -> list[str]:
        """ssh bis einschließlich Ziel; options stehen vor dem Ziel, etwa für einen Tunnel."""
        return ["ssh", *(("-J", self.jump) if self.jump else ()), *options, self.host]

    def argv(self) -> list[str]:
        return [*self.ssh(), "bash", "-s"]

    def __str__(self) -> str:
        return self.host + (f" über {self.jump}" if self.jump else "")

    def run(self, script: str, timeout: float = 60) -> str:
        done = subprocess.run(self.argv(), input=script, capture_output=True, text=True,
                              timeout=timeout, check=False)
        if done.returncode != 0 and not done.stdout:
            raise RuntimeError(f"ssh: {done.stderr.strip() or done.returncode}")
        return done.stdout

    def facts(self) -> dict:
        parts = sections(self.run(FACTS_SCRIPT.format(dir=shlex.quote(self.directory))))
        mem = meminfo_bytes(parts.get("meminfo", ""))
        env = parts.get("env", "")
        threads, source = threads_from_env(env)
        nproc = parts.get("nproc", "").strip()
        return {"vcpu": int(nproc) if nproc.isdigit() else None,
                "ram_bytes": mem.get("MemTotal"), "threads": threads, "threads_quelle": source,
                "env": env, "inspect": inspect_summary(parts.get("inspect", ""))}

    def inspect(self, ids: dict[str, str]) -> dict:
        if not ids:
            return {}
        # Fehlt ein Container, nennt docker inspect nur die übrigen; container_breaks meldet ihn.
        quoted = " ".join(map(shlex.quote, ids.values()))
        return inspect_summary(self.run(f"docker inspect {quoted} 2>/dev/null </dev/null\n"))

    def sampler(self, ids: dict[str, str], path: Path) -> Sampler:
        script = SAMPLER_SCRIPT.replace("IDS", " ".join(map(shlex.quote, ids.values())))
        return Sampler(self.argv(), script, ids, path)


class Sampler:
    """Liest die Ausgabe der Sampler-Schleife auf der VM und schreibt samples.jsonl. Die Zeit
    nimmt es beim Eintreffen jedes Blocks von der eigenen Uhr, damit sie zu requests.jsonl passt."""

    def __init__(self, argv: list[str], script: str, ids: dict[str, str], path: Path):
        self.ids, self.path = ids, path
        self.proc = subprocess.Popen(argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                     stderr=subprocess.DEVNULL, text=True, bufsize=1)
        self.proc.stdin.write(script)
        self.proc.stdin.close()
        self.thread = threading.Thread(target=self._read, daemon=True)
        self.thread.start()

    def _read(self) -> None:
        block: tuple[str, list[str]] | None = None
        cpu = None
        with self.path.open("a", encoding="utf-8") as out:
            for line in self.proc.stdout:
                line = line.rstrip("\n")
                if line == "@@":
                    if block is not None:
                        sample, cpu = parse_sample(block[0], block[1], cpu, self.ids)
                        out.write(json.dumps(sample, ensure_ascii=False) + "\n")
                        out.flush()
                    block = (now_iso(), [])
                elif block is not None:
                    block[1].append(line)

    def stop(self) -> None:
        self.proc.terminate()
        try:
            self.proc.wait(5)
        except subprocess.TimeoutExpired:
            self.proc.kill()
        self.thread.join(5)


@contextmanager
def tunnel(vm: VM, host: str, port: int):
    """ssh -L auf einen freien lokalen Port; liefert die URL der App."""
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        local = s.getsockname()[1]
    argv = vm.ssh("-N", "-o", "ExitOnForwardFailure=yes", "-L", f"127.0.0.1:{local}:{host}:{port}")
    proc = subprocess.Popen(argv, stdin=subprocess.DEVNULL)
    try:
        deadline = time.monotonic() + 30
        while True:
            if proc.poll() is not None:
                sys.exit(f"SSH-Tunnel beendet (Exit {proc.returncode}).")
            try:
                socket.create_connection(("127.0.0.1", local), timeout=1).close()
                break
            except OSError:
                if time.monotonic() > deadline:
                    sys.exit("SSH-Tunnel steht nach 30 s noch nicht.")
                time.sleep(0.5)
        yield f"http://127.0.0.1:{local}"
    finally:
        proc.terminate()
        try:
            proc.wait(5)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()


# ---------- Last ----------

@dataclass(frozen=True)
class StageRules:
    min_requests: int
    min_duration_s: float


async def check(client: httpx.AsyncClient, text: str, gate_threshold: float) -> dict:
    """Eine Prüfung wie aus der UI, mit Kennzeichnung im Request-Log."""
    body = {"text": text, "gate_threshold": gate_threshold, "force": False, "use_laya_check": True}
    start = now_iso()
    t0 = time.perf_counter()
    status = timing = note = error = None
    try:
        async with asyncio.timeout(CLIENT_TIMEOUT_S):
            response = await client.post("/api/analyze", json=body, headers=HEADERS)
        status = response.status_code
        if status == 200:
            try:
                data = response.json()
                timing, note = data["timing"], data["gate"].get("note") or None
            except (ValueError, KeyError, TypeError, AttributeError):
                error = "Antwort ist kein lesbares JSON"
        else:
            error = f"HTTP {status}: {_detail(response)}"
    except TimeoutError:
        error = f"Client-Timeout nach {CLIENT_TIMEOUT_S} s"
    except httpx.HTTPError as exc:
        error = f"{type(exc).__name__}: {exc}"[:300]
    return {"start": start, "client_ms": round((time.perf_counter() - t0) * 1000),
            "status": status, "klasse": ev.classify(status, note, error),
            "timing": timing, "gate_note": note, "fehler": error}


def _detail(response: httpx.Response) -> str:
    try:
        return str(response.json().get("detail"))[:200]
    except (ValueError, AttributeError):
        return response.text[:200]


async def run_stage(client: httpx.AsyncClient, part: str, stage: int,
                    examples: list[tuple[str, str]], gate_threshold: float, rules: StageRules,
                    write: Callable[[dict], None], long: str | None = None) -> None:
    """Eine Stufe: stage Nutzer schicken ohne Pause die nächste Prüfung, sobald die vorige zurück
    ist (nach einer fehlgeschlagenen erst nach FAILED_PAUSE_S). Ist die Stufe voll, schickt
    keiner mehr, die offenen Anfragen laufen leer. Mit long schickt Nutzer 1 nur den Langtext;
    seine Anfragen zählen nicht für die Stufenregel."""
    stop = asyncio.Event()
    started = time.monotonic()
    counted = 0

    def check_done() -> None:
        if counted >= rules.min_requests and time.monotonic() - started >= rules.min_duration_s:
            stop.set()

    async def user(n: int) -> None:
        nonlocal counted
        texts = [(ev.LONG_TEXT, long)] if long and n == 1 else user_order(examples, n)
        i = 0
        while not stop.is_set():
            name, text = texts[i % len(texts)]
            result = await check(client, text, gate_threshold)
            write({"abschnitt": part, "stufe": stage, "nutzer": n, "aufwaermen": i == 0,
                   "beispiel": name, "zeichen": len(text), **result})
            if i > 0 and name != ev.LONG_TEXT:
                counted += 1
            check_done()
            i += 1
            if result["klasse"] == ev.FAILED and not stop.is_set():
                await asyncio.sleep(FAILED_PAUSE_S)

    async def clock() -> None:
        last = started
        while not stop.is_set():
            await asyncio.sleep(1)
            check_done()
            if time.monotonic() - last >= 30 and not stop.is_set():
                last = time.monotonic()
                print(f"    … {counted} gezählt nach {last - started:.0f} s", flush=True)

    await asyncio.gather(clock(), *(user(n) for n in range(1, stage + 1)))


# ---------- Ablauf ----------

def now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds")


def get_json(url: str, path: str) -> dict:
    """GET auf die App. Antwortet sie nicht oder nicht lesbar, endet das Skript mit einer Meldung
    statt mit einem Traceback: Vor dem Start ist das die ganze Antwort."""
    try:
        response = httpx.get(url + path, timeout=30)
        response.raise_for_status()
        return response.json()
    except (httpx.HTTPError, ValueError) as exc:
        sys.exit(f"App antwortet nicht lesbar auf {path} unter {url}: {exc}")


def wait_for_calibration(url: str) -> dict:
    deadline = time.monotonic() + CALIBRATION_WAIT_S
    while True:
        config = get_json(url, "/api/config")
        if config.get("calibration"):
            return config
        if time.monotonic() > deadline:
            health = get_json(url, "/api/health")
            sys.exit(f"Nach {CALIBRATION_WAIT_S // 60} min noch keine Kalibrierung. Ohne Laya beim "
                     f"Start bleibt sie aus; /api/health meldet für Laya: {health.get('laya')!r}")
        print("  Kalibrierung läuft noch, warte …", flush=True)
        time.sleep(10)


class Run:
    """Ein Lauf mit seinen Dateien. run.json wird zu Beginn und am Ende geschrieben."""

    def __init__(self, directory: Path, meta: dict):
        # Zwei Läufe in derselben Minute bekämen denselben Namen.
        self.dir, n = directory, 1
        while self.dir.exists():
            n += 1
            self.dir = directory.with_name(f"{directory.name}-{n}")
        self.dir.mkdir(parents=True)
        self.meta = meta
        self.requests: list[dict] = []
        self._out = (self.dir / "requests.jsonl").open("a", encoding="utf-8")
        (self.dir / "samples.jsonl").touch()
        self.save()

    def write(self, record: dict) -> None:
        self.requests.append(record)
        self._out.write(json.dumps(record, ensure_ascii=False) + "\n")
        self._out.flush()

    def save(self) -> None:
        (self.dir / "run.json").write_text(json.dumps(self.meta, ensure_ascii=False, indent=1),
                                           encoding="utf-8")

    def evaluate(self) -> dict:
        return ev.evaluate_run(self.requests, self.meta["stufen"],
                               ev.read_jsonl(self.dir / "samples.jsonl"))

    def close(self) -> None:
        self._out.close()


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--url", help="App direkt ansprechen, ohne SSH-Tunnel (make up, Caddy)")
    ap.add_argument("--vm", action="store_true", help="mit --url die VM trotzdem per ssh mitlesen")
    ap.add_argument("--label", help="Zusatz im Namen des Ergebnisverzeichnisses")
    ap.add_argument("--stages", default=",".join(map(str, LADDER)),
                    help="Treppe, kommagetrennt (Standard: %(default)s)")
    ap.add_argument("--min-requests", type=int, default=MIN_REQUESTS,
                    help="gezählte Prüfungen je Stufe mindestens (Standard: %(default)s)")
    ap.add_argument("--min-duration", type=float, default=MIN_STAGE_S,
                    help="Sekunden je Stufe mindestens (Standard: %(default)s)")
    ap.add_argument("--no-longtext", action="store_true", help="Langtext-Wiederholung auslassen")
    ap.add_argument("--out", type=Path, default=RESULTS,
                    help="Ablage (Standard: loadtest-results/)")
    args = ap.parse_args()
    try:
        args.stages = [int(s) for s in args.stages.split(",") if s.strip()]
    except ValueError:
        ap.error("--stages erwartet Zahlen, z. B. 1,2,4")
    if not args.stages or min(args.stages) < 1:
        ap.error("--stages braucht mindestens eine Stufe ≥ 1")
    return args


def keep_awake() -> None:
    """Kein Ruhezustand bei Leerlauf, solange dieser Prozess läuft: caffeinate auf dem Mac,
    systemd-inhibit unter Linux. Fehlt beides, steht ein Hinweis auf der Konsole."""
    pid = str(os.getpid())
    if shutil.which("caffeinate"):
        argv = ["caffeinate", "-i", "-w", pid]
    elif shutil.which("systemd-inhibit"):
        argv = ["systemd-inhibit", "--what=idle:sleep", "--who=fidelius-lasttest",
                "--why=Lasttest läuft", "tail", f"--pid={pid}", "-f", "/dev/null"]
    else:
        print("HINWEIS: Weder caffeinate noch systemd-inhibit gefunden. Schläft der Rechner "
              "während des Laufs ein, misst die Stufe Unsinn.")
        return
    subprocess.Popen(argv, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def main() -> int:
    args = parse_args()
    examples = load_examples()
    keep_awake()
    vm = VM.from_env() if not args.url or args.vm else None
    facts = None
    if vm:
        print(f"VM: lese {vm}, Verzeichnis {vm.directory} …", flush=True)
        facts = _facts(vm)
        if not facts["inspect"]:
            print("  WARNUNG: keine Container app und laya gefunden, Brüche durch Neustart "
                  "bleiben unerkannt.")
        print(f"  {facts['vcpu']} vCPU, {ev.gib(facts['ram_bytes'])} RAM, "
              f"OMP_NUM_THREADS {facts['threads']} ({facts['threads_quelle']})")
        _warn_threads(facts)

    with _access(args, vm, facts) as (url, access):
        print(f"Ziel: {url}", flush=True)
        health = get_json(url, "/api/health")
        if not isinstance(health.get("laya"), dict):
            print(f"  WARNUNG: Laya meldet {health.get('laya')!r}")
        config = wait_for_calibration(url)
        build, calibration = config.get("build") or {}, config["calibration"]
        rate = ev.num(calibration['rate_ms_per_char'], 2)
        print(f"  Build #{build.get('number')} · {build.get('commit')}"
              f"{'*' if build.get('dirty') else ''}, Kalibrierung "
              f"{calibration['base_ms']:.0f} ms + {rate} ms/Zeichen", flush=True)

        started = datetime.now().astimezone()
        # Ohne VM sind Größe, Threads und Container unbekannt.
        size = {k: facts[k] if facts else None
                for k in ("vcpu", "ram_bytes", "threads", "threads_quelle")}
        inspect = facts["inspect"] if facts else None
        name = result_dir_name(started, size["vcpu"], size["threads"], args.label)
        ids = {s: c["id"] for s, c in (inspect or {}).items()}
        run = Run(args.out / name, {
            "zeit": started.astimezone(UTC).isoformat(timespec="milliseconds"), "ende": None,
            "label": args.label, "zugang": access, **size,
            "build": build, "kalibrierung": calibration,
            "gate_threshold": config["gate_threshold"],
            "parameter": {"stufen": args.stages, "min_anfragen": args.min_requests,
                          "min_dauer_s": args.min_duration, "client_timeout_s": CLIENT_TIMEOUT_S,
                          "langtext": not args.no_longtext},
            "docker_inspect_vorher": inspect,
            "docker_inspect_nachher": None, "stufen": [], "abbruch": None,
        })
        print(f"Ablage: {run.dir.relative_to(ROOT) if run.dir.is_relative_to(ROOT) else run.dir}")
        sampler = vm.sampler(ids, run.dir / "samples.jsonl") if vm and ids else None
        try:
            asyncio.run(_ladder(run, url, examples, args, vm, ids))
        except KeyboardInterrupt:
            run.meta["abbruch"] = "Strg-C"
            print("\nAbgebrochen, die Ablage enthält, was bis hierhin fertig war.")
        finally:
            if sampler:
                sampler.stop()
            run.meta["ende"] = now_iso()
            if vm and ids:
                after = _inspect(vm, ids)
                run.meta["docker_inspect_nachher"] = after
                lost = after is not None and ev.container_breaks(
                    run.meta["docker_inspect_vorher"], after)
                if lost:
                    print("WARNUNG: Container seit Beginn: " + ", ".join(lost))
                if not ev.read_jsonl(run.dir / "samples.jsonl"):
                    print("WARNUNG: Der Sampler hat keine Messwerte geliefert.")
            run.save()
            run.close()
        print()
        print(format_table(run.evaluate()))
    return 130 if run.meta["abbruch"] else 0


def _facts(vm: VM) -> dict:
    """vm.facts(), oder Schluss mit einer Meldung, wenn ssh scheitert: Ohne die Größe der VM
    lässt sich der Lauf nicht einordnen."""
    try:
        return vm.facts()
    except (RuntimeError, OSError, subprocess.TimeoutExpired) as exc:
        sys.exit(f"VM {vm} nicht lesbar: {exc}")


def _inspect(vm: VM, ids: dict) -> dict | None:
    """docker inspect, oder None, wenn ssh scheitert. Das ist kein Bruch nach der Spec, aber
    der Hinweis gehört auf die Konsole: Reagiert die VM nicht mehr, ist das die Antwort."""
    try:
        return vm.inspect(ids)
    except (RuntimeError, OSError, subprocess.TimeoutExpired) as exc:
        print(f"  WARNUNG: docker inspect auf der VM nicht lesbar: {exc}", flush=True)
        return None


@contextmanager
def _access(args, vm: VM | None, facts: dict | None):
    if args.url:
        url = args.url.rstrip("/")
        yield url, {"url": url, "tunnel": None, "vm": vm is not None}
        return
    host, port = tunnel_target(os.environ.get("DEPLOY_BIND"), facts["env"])
    with tunnel(vm, host, port) as url:
        yield url, {"url": url, "vm": True,
                    "tunnel": {"host": vm.host, "jump": vm.jump, "ziel": f"{host}:{port}"}}


async def _ladder(run: Run, url: str, examples, args, vm: VM | None, ids: dict) -> None:
    rules = StageRules(args.min_requests, args.min_duration)
    gate_threshold = run.meta["gate_threshold"]
    limits = httpx.Limits(max_connections=max(args.stages) + 5)
    async with httpx.AsyncClient(base_url=url, timeout=CLIENT_TIMEOUT_S + 10,
                                 limits=limits) as client:
        state = run.meta["docker_inspect_vorher"]

        async def stage(part: str, n: int, long: str | None = None) -> None:
            nonlocal state
            label = "Langtext, Stufe" if long else "Stufe"
            print(f"{label} {n}: {n} gleichzeitig …", flush=True)
            meta = {"abschnitt": part, "stufe": n, "start": now_iso(), "ende": None,
                    "container_bruch": []}
            run.meta["stufen"].append(meta)
            await run_stage(client, part, n, examples, gate_threshold, rules, run.write, long)
            meta["ende"] = now_iso()
            if vm and ids:
                after = await asyncio.to_thread(_inspect, vm, ids)
                if after is not None:
                    meta["container_bruch"] = ev.container_breaks(state, after)
                    state = after
            run.save()

        for n in args.stages:
            await stage(ev.LADDER_PART, n)
            result = run.evaluate()
            row = next(s for s in result["stages"] if s["stage"] == n)
            print("  " + _row_summary(row), flush=True)
            if result["break_stage"] == n:
                print(f"  Bruch: {', '.join(row['breaks'])}. Die Treppe endet hier.")
                break

        c_star = run.evaluate()["c_star"]
        if args.no_longtext:
            return
        if c_star is None:
            print("Langtext ausgelassen: Keine Stufe hält die Komfortgrenze, c* fehlt.")
            return
        if c_star < 2:
            print("Langtext ausgelassen: c* = 1, neben dem Langtext-Nutzer gäbe es keine anderen, "
                  "deren p95 sich vergleichen ließe.")
            return
        await stage(ev.LONG_TEXT_PART, c_star, long_text(examples))


# ---------- Konsole ----------

def _s(ms) -> str:
    """Millisekunden als Sekunden mit einer Nachkommastelle, ohne Einheit."""
    return ev.num(None if ms is None else ms / 1000)


def _row_summary(row: dict) -> str:
    c = row["classes"]
    return (f"p50 {_s(row['p50_ms'])} s, p95 {_s(row['p95_ms'])} s, {row['count']} gezählt, "
            + ", ".join(f"{c[k]} {k}" for k in ev.CLASSES))


def _warn_threads(facts: dict) -> None:
    vcpu, threads = facts["vcpu"], facts["threads"]
    if vcpu and threads != max(1, vcpu // 2):
        print(f"  WARNUNG: OMP_NUM_THREADS {threads} weicht von vCPU/2 = {vcpu // 2} ab.")
    running = {s: c.get("omp_num_threads") for s, c in facts["inspect"].items()}
    stale = [s for s, v in running.items() if v is not None and v != str(threads)]
    if stale:
        print(f"  WARNUNG: {', '.join(stale)} läuft mit OMP_NUM_THREADS "
              f"{', '.join(running[s] for s in stale)}, die .env sagt {threads}. "
              "Compose nach der Änderung neu gestartet?")


def format_table(result: dict) -> str:
    head = (f"{'Stufe':>5} {'gezählt':>7} {'p50 s':>6} {'p95 s':>6} {'max s':>6} {'Prüf./min':>9} "
            f"{'ok':>4} {'degr.':>5} {'fehlg.':>6}  Komfort  Bruch")
    lines = [head, "-" * len(head)]
    for s in result["stages"]:
        c = s["classes"]
        tp = ev.num(s["throughput_per_min"])
        lines.append(f"{s['stage']:>5} {s['count']:>7} {_s(s['p50_ms']):>6} {_s(s['p95_ms']):>6} "
                     f"{_s(s['max_ms']):>6} {tp:>9} {c[ev.OK]:>4} {c[ev.DEGRADED]:>5} "
                     f"{c[ev.FAILED]:>6}  {'ja' if s['comfort'] else 'nein':<7}  "
                     f"{', '.join(s['breaks'])}")
    lines.append("")
    lt = result["longtext"]
    if lt:
        lines.append(f"Langtext bei Stufe {lt['stage']}: p95 der anderen "
                     f"{_s(lt['others']['p95_ms'])} s ({lt['others']['count']} gezählt), in der "
                     f"Treppe {_s(lt['ladder_p95_ms'])} s; Langtext selbst p50 "
                     f"{_s(lt['long']['p50_ms'])} s")
    lines.append(f"c* = {result['c_star'] if result['c_star'] is not None else '–'} "
                 f"(Komfortgrenze p95 ≤ {ev.COMFORT_P95_MS // 1000} s)")
    breaking = next((s for s in result["stages"] if s["stage"] == result["break_stage"]), None)
    lines.append(f"Bruchstufe: {breaking['stage']}, {', '.join(breaking['breaks'])}"
                 if breaking else "Bruchstufe: keine erreicht")
    if result["ram_peak_bytes"] is not None:
        lines.append(f"RAM-Spitze der VM: {ev.gib(result['ram_peak_bytes'])}")
    return "\n".join(lines)


if __name__ == "__main__":
    sys.exit(main())
