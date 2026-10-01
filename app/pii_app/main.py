"""FastAPI-App: API-Endpunkte und statische Web-UI."""
from __future__ import annotations

import logging
import os
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from . import config
from .detectors import gliner, spacy_det
from .models import AnalyzeRequest, AnalyzeResponse, ApplyRequest, ApplyResponse
from .pipeline import Pipeline

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger(__name__)

app = FastAPI(title="PII-Anonymisierung vor dem Prompting", version="0.1.0")
pipeline = Pipeline()
STATIC = Path(__file__).parent / "static"


@app.on_event("startup")
def _warmup() -> None:
    gliner.warmup()
    spacy_det.warmup()
    log.info("Modelle geladen.")


@app.middleware("http")
async def no_cache(request: Request, call_next):
    """UI und API nie cachen: nach einem Rebuild soll der Browser sofort die neue Oberfläche laden."""
    response = await call_next(request)
    response.headers["Cache-Control"] = "no-cache"
    return response


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


@app.post("/api/analyze", response_model=AnalyzeResponse)
def analyze(req: AnalyzeRequest) -> AnalyzeResponse:
    if not req.text.strip():
        raise HTTPException(400, "Leerer Text")
    return pipeline.analyze(req)


@app.post("/api/apply", response_model=ApplyResponse)
def apply(req: ApplyRequest) -> ApplyResponse:
    entities, anonymized, mapping = pipeline.apply(req.text, req.entities)
    return ApplyResponse(entities=entities, anonymized_text=anonymized, mapping=mapping)


@app.get("/")
def index() -> FileResponse:
    return FileResponse(STATIC / "index.html")


app.mount("/static", StaticFiles(directory=STATIC), name="static")
