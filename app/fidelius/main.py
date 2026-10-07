"""FastAPI-App: API-Endpunkte und statische Web-UI."""
from __future__ import annotations

import logging
import os
from pathlib import Path

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from . import build_info, config, log_report
from .calibration import Calibration
from .detectors import gliner, spacy_det
from .models import AnalyzeRequest, AnalyzeResponse, ApplyRequest, ApplyResponse
from .pipeline import Pipeline

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger(__name__)

app = FastAPI(title="PII-Anonymisierung vor dem Prompting", version=build_info.version())
pipeline = Pipeline(log_path=config.REQUEST_LOG)
calibration = Calibration(pipeline, config.EXAMPLES_DIR)
STATIC = Path(__file__).parent / "static"


@app.on_event("startup")
def _warmup() -> None:
    gliner.warmup()
    spacy_det.warmup()
    log.info("Modelle geladen.")
    calibration.start()


@app.middleware("http")
async def no_cache(request: Request, call_next):
    """UI und API nie cachen: nach einem Rebuild soll der Browser sofort die neue Oberfläche laden."""
    response = await call_next(request)
    response.headers["Cache-Control"] = "no-cache"
    return response


@app.middleware("http")
async def limit_body(request: Request, call_next):
    """Zu große Anfragen ablehnen, bevor der Body gelesen wird. Ohne Content-Length (chunked)
    ließe sich die Grenze umgehen, deshalb muss ein POST ihn mitschicken; fetch tut das immer."""
    if request.method == "POST":
        length = request.headers.get("content-length")
        if length is None or not length.isdigit():
            return JSONResponse({"detail": "Content-Length fehlt"}, status_code=411)
        if int(length) > config.MAX_BODY_BYTES:
            return JSONResponse({"detail": "Die Anfrage ist zu groß"}, status_code=413)
    return await call_next(request)


@app.get("/api/health")
def health() -> dict:
    laya: dict | str
    try:
        laya = pipeline.laya.health()
    except Exception as exc:
        laya = f"nicht erreichbar: {exc.__class__.__name__}"
    return {"status": "ok", "laya": laya, "laya_url": config.LAYA_URL}


@app.get("/api/config")
def get_config() -> dict:
    return {
        "categories": config.CATEGORIES,
        "gate_threshold": config.GATE_THRESHOLD,
        "laya_reject_threshold": config.LAYA_REJECT_THRESHOLD,
        "laya_checked_categories": sorted(config.LAYA_CHECKED_CATEGORIES),
        "max_text_chars": config.MAX_TEXT_CHARS,
        "calibration": calibration.as_dict(),
        "build": build_info.build(),
    }


@app.get("/api/examples")
def list_examples() -> list[dict]:
    d = Path(config.EXAMPLES_DIR)
    if not d.is_dir():
        return []
    out = []
    for p in sorted(d.glob("*.txt")):
        first = p.read_text(encoding="utf-8").splitlines()
        subject = next((l[len("Betreff:"):].strip() for l in first if l.startswith("Betreff:")), p.stem)
        out.append({"name": p.stem, "title": subject})
    return out


@app.get("/api/examples/{name}")
def get_example(name: str) -> dict:
    p = Path(config.EXAMPLES_DIR) / f"{os.path.basename(name)}.txt"
    if not p.is_file():
        raise HTTPException(404, "Beispiel nicht gefunden")
    return {"name": p.stem, "text": p.read_text(encoding="utf-8")}


def _check_length(text: str) -> None:
    if len(text) > config.MAX_TEXT_CHARS:
        def de(n: int) -> str:
            return f"{n:,}".replace(",", ".")
        raise HTTPException(413, f"Der Text ist zu lang ({de(len(text))} Zeichen, höchstens {de(config.MAX_TEXT_CHARS)})")


@app.post("/api/analyze", response_model=AnalyzeResponse)
def analyze(
    req: AnalyzeRequest,
    quelle: str | None = Header(default=None, alias="X-Fidelius-Quelle"),
) -> AnalyzeResponse:
    """Der Header kennzeichnet Lasttest-Anfragen im Request-Log (docs/specs/lasttest.md)."""
    if not req.text.strip():
        raise HTTPException(400, "Leerer Text")
    _check_length(req.text)
    return pipeline.analyze(req, source="lasttest" if quelle == "lasttest" else "anfrage")


@app.post("/api/apply", response_model=ApplyResponse)
def apply(req: ApplyRequest) -> ApplyResponse:
    _check_length(req.text)
    if len(req.entities) > config.MAX_ENTITIES:
        raise HTTPException(413, f"Zu viele Stellen ({len(req.entities)}, höchstens {config.MAX_ENTITIES})")
    entities, anonymized, mapping = pipeline.apply(req.text, req.entities)
    return ApplyResponse(entities=entities, anonymized_text=anonymized, mapping=mapping)


@app.get("/api/report")
def get_report(period: str = "30d") -> dict:
    """Fehlt das Log, kommt trotzdem eine Antwort mit log.present = false und dem Pfad."""
    try:
        return log_report.report(config.REQUEST_LOG, period)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@app.get("/api/request-log")
def get_request_log() -> FileResponse:
    p = Path(config.REQUEST_LOG)
    if not p.is_file():
        raise HTTPException(404, f"Kein Request-Log vorhanden ({p})")
    return FileResponse(p, media_type="application/x-ndjson", filename="requests.jsonl")


@app.get("/")
def index() -> FileResponse:
    return FileResponse(STATIC / "index.html")


@app.get("/auswertung")
def report_page() -> FileResponse:
    return FileResponse(STATIC / "report.html")


app.mount("/static", StaticFiles(directory=STATIC), name="static")
