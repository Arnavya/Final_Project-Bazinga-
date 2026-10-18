# Expert-Learning Organizational Reasoning Engine — container image.
#
#   docker build -t reasoning-engine:dev \
#     --build-arg APP_VERSION=1.0.0 --build-arg GIT_SHA=$(git rev-parse HEAD) .
#   docker run --rm -p 8501:8501 reasoning-engine:dev
#
# The image runs fully offline by default (hashing embedder, stub LLM when no key).
# Pass GROQ_API_KEY at run time (never at build time) to use the Groq LLM.
#
# Behind a TLS-intercepting proxy, give pip the proxy CA without baking it into a layer:
#   docker build --secret id=pip_ca,src=/path/to/ca.crt ...

ARG BASE_IMAGE=python:3.12-slim

# ---------------------------------------------------------------- build stage
FROM ${BASE_IMAGE} AS build

ENV PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

# Dependencies first so code changes do not invalidate this layer.
COPY requirements-runtime.txt .
RUN --mount=type=secret,id=pip_ca,required=false \
    if [ -f /run/secrets/pip_ca ]; then export PIP_CERT=/run/secrets/pip_ca; fi; \
    python3 -m venv /opt/venv \
 && /opt/venv/bin/pip install --no-compile -r requirements-runtime.txt

COPY engine/ engine/
COPY ingest/ ingest/
COPY data/ data/

# Build the dataset and the stores into a read-only seed directory. The embedder used here
# must match the one used at run time, so both are pinned to the offline hashing embedder.
ENV EMBEDDING_MODEL=hashing \
    LLM_PROVIDER=stub \
    STORES_DIR=/app/stores-seed
RUN /opt/venv/bin/python data/build_dataset.py \
 && /opt/venv/bin/python -m ingest.build_vectors \
 && /opt/venv/bin/python -m ingest.build_graph \
 && /opt/venv/bin/python -m engine.health

# -------------------------------------------------------------- runtime stage
FROM ${BASE_IMAGE} AS runtime

ARG APP_VERSION=dev
ARG GIT_SHA=unknown

LABEL org.opencontainers.image.title="reasoning-engine" \
      org.opencontainers.image.description="Expert-Learning Organizational Reasoning Engine (Streamlit)" \
      org.opencontainers.image.version="${APP_VERSION}" \
      org.opencontainers.image.revision="${GIT_SHA}"

# Fixed non-root UID/GID so Kubernetes runAsUser and volume ownership line up.
RUN groupadd --system --gid 10001 app \
 && useradd --system --uid 10001 --gid 10001 --home-dir /app --shell /usr/sbin/nologin app

ENV PATH="/opt/venv/bin:${PATH}" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    HOME=/tmp \
    APP_VERSION=${APP_VERSION} \
    GIT_SHA=${GIT_SHA} \
    EMBEDDING_MODEL=hashing \
    LLM_PROVIDER=groq \
    STORES_DIR=/app/stores \
    LOG_FORMAT=json \
    LOG_LEVEL=INFO

WORKDIR /app

COPY --from=build /opt/venv /opt/venv
COPY --from=build /app/data /app/data
COPY --from=build /app/stores-seed /app/stores-seed
COPY engine/ engine/
COPY ingest/ ingest/
COPY .streamlit/ .streamlit/
COPY app.py pipeline.py run_all.py run_scenario.py ./
COPY docker/entrypoint.sh /usr/local/bin/entrypoint.sh

# Code and seed are root-owned and read-only to the app user; only the state dir is writable.
RUN chmod 0755 /usr/local/bin/entrypoint.sh \
 && mkdir -p /app/stores \
 && chown 10001:10001 /app/stores

USER 10001:10001

EXPOSE 8501

# Liveness of the web server. Readiness (stores usable) is `python -m engine.health`.
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
  CMD ["python3", "-c", "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8501/_stcore/health', timeout=4).read().strip() == b'ok' else 1)"]

ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
CMD ["streamlit", "run", "app.py", "--server.port=8501", "--server.address=0.0.0.0"]
