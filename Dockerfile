FROM python:3.12-slim AS runtime
ARG NEBIUS_CLI_VERSION=0.12.295
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends curl ca-certificates libgomp1 && rm -rf /var/lib/apt/lists/*
RUN curl -fsSL "https://artifacts.nebius.cloud/cli/release/${NEBIUS_CLI_VERSION}/linux/x86_64/nebius" -o /usr/local/bin/nebius && chmod +x /usr/local/bin/nebius
RUN pip install --no-cache-dir tavily-cli==0.1.8
RUN useradd --create-home --uid 1000 haunted && mkdir -p /app/data && chown haunted:haunted /app/data
ENV HOST=0.0.0.0 PORT=8080 GAME_DATA_DIR=/app/runtime-data/runtime CARETAKER_BASE_DIR=/opt/models/base PYTHONUNBUFFERED=1 HF_HUB_OFFLINE=1 TOKENIZERS_PARALLELISM=false
EXPOSE 8080
HEALTHCHECK --interval=30s --start-period=120s --timeout=5s CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/healthz', timeout=3)"
CMD ["python", "deploy/bootstrap.py"]

# Stable model dependencies do not rebuild for front-end or game-code edits.
FROM runtime AS cpu-dependencies
COPY requirements-model.txt .
RUN pip install --no-cache-dir torch==2.14.1 --index-url https://download.pytorch.org/whl/cpu && pip install --no-cache-dir -r requirements-model.txt
RUN HF_HUB_OFFLINE=0 hf download Qwen/Qwen3-0.6B --revision c1899de289a04d12100db370d81485cdf75e47ca --local-dir /opt/models/base

FROM runtime AS app
COPY --chown=haunted:haunted *.py ./
COPY --chown=haunted:haunted web ./web
COPY --chown=haunted:haunted data ./data
COPY --chown=haunted:haunted puzzles ./puzzles
COPY --chown=haunted:haunted solutions ./solutions
COPY deploy/bootstrap.py ./deploy/bootstrap.py

# Optional compatibility image also serves earlier managed-training saves.
FROM cpu-dependencies AS cpu
COPY --from=app /app /app

# Default: the model lives on the warm Serverless GPU.
FROM app AS stream
