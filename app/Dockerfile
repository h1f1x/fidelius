# Web-App mit GLiNER2-PII, spaCy (de_core_news_lg) und Regex-Erkennern. Modelle werden beim
# Build geladen, damit der Container danach ohne Internet startet (HF_HUB_OFFLINE=1 in compose).
FROM python:3.12-slim-bookworm
ENV PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 \
    TOKENIZERS_PARALLELISM=false OMP_NUM_THREADS=4 \
    HF_HOME=/opt/hf-cache
WORKDIR /opt/app
RUN pip install "torch==2.14.0" --index-url https://download.pytorch.org/whl/cpu
COPY pyproject.toml ./
RUN pip install \
      "fastapi>=0.115" "uvicorn[standard]>=0.30" "httpx>=0.27" "pydantic>=2.7" \
      "gliner2[local]==2.0.0" "transformers==4.51.3" "sentencepiece>=0.2" "protobuf>=4" "spacy>=3.8,<3.9" \
      "google-re2>=1.1" \
    && python -m spacy download de_core_news_lg \
    && pip check
# Ab hier ohne root: Die Gewichte landen im Cache des App-Users, und die App läuft als dieser User.
# Das Log-Verzeichnis gehört ihm schon im Image, weil ein neues benanntes Volume Eigentümer und
# Rechte vom Image-Verzeichnis übernimmt; sonst gehörte es root und das Request-Log bliebe leer.
RUN groupadd --gid 10001 app \
    && useradd --uid 10001 --gid app --create-home app \
    && mkdir -p "$HF_HOME" /var/log/fidelius && chown app:app "$HF_HOME" /var/log/fidelius
USER app
# GLiNER2-PII einmal laden, damit die Gewichte im Image liegen.
RUN python -c "from gliner2 import GLiNER2; GLiNER2.from_pretrained('fastino/gliner2-privacy-filter-PII-multi')"
COPY fidelius ./fidelius
# Build-Stand für die UI, von scripts/build-info.sh. Steht zuletzt, weil BUILD_TIME sich bei jedem
# Build ändert und sonst den Cache aller Layer darunter verwerfen würde.
ARG BUILD_NUMBER= BUILD_COMMIT= BUILD_DIRTY= BUILD_TIME=
ENV BUILD_NUMBER=$BUILD_NUMBER BUILD_COMMIT=$BUILD_COMMIT BUILD_DIRTY=$BUILD_DIRTY BUILD_TIME=$BUILD_TIME
EXPOSE 8080
CMD ["uvicorn", "fidelius.main:app", "--host", "0.0.0.0", "--port", "8080"]
