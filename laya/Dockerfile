# Laya-Server (Convai Innovations, Apache 2.0) als eigenständiger Dienst, CPU-Betrieb.
# Angelehnt an das Upstream-Dockerfile, aber aus dem PyPI-Paket statt aus dem Checkout gebaut.
ARG PYTHON_IMAGE=python:3.11-slim-bookworm
FROM ${PYTHON_IMAGE} AS build
ENV PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"
ARG TORCH_VERSION=2.14.0
RUN pip install "torch==${TORCH_VERSION}" --index-url https://download.pytorch.org/whl/cpu
RUN pip install "laya[serve]==0.3.22" && pip check

FROM ${PYTHON_IMAGE} AS runtime
ENV PATH="/opt/venv/bin:$PATH" \
    TORCH_DISABLE_NATIVE_JIT=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    USE_TF=0 USE_TORCH=1 \
    TOKENIZERS_PARALLELISM=false \
    OMP_NUM_THREADS=4 \
    LAYA_DEVICE=cpu \
    LAYA_HOST=0.0.0.0 \
    LAYA_PORT=8000 \
    HF_HOME=/home/laya/.cache/huggingface
RUN groupadd --gid 10001 laya \
    && useradd --uid 10001 --gid laya --create-home laya \
    && mkdir -p /home/laya/.cache/huggingface \
    && chown -R laya:laya /home/laya/.cache
COPY --from=build /opt/venv /opt/venv
USER laya
WORKDIR /home/laya
EXPOSE 8000
CMD ["laya-serve"]
