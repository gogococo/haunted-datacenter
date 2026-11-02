FROM python:3.12-slim AS base
WORKDIR /app
ENV PYTHONUNBUFFERED=1 TOKENIZERS_PARALLELISM=false OMP_NUM_THREADS=4 MKL_NUM_THREADS=4
RUN useradd --create-home --uid 1000 haunted && mkdir /data && chown haunted:haunted /data
USER haunted

FROM base AS worker
USER root
RUN pip install --no-cache-dir torch==2.8.0 --index-url https://download.pytorch.org/whl/cpu && \
    pip install --no-cache-dir transformers==4.57.1 peft==0.17.1 accelerate==1.10.1 safetensors==0.6.2
USER haunted
COPY *.py ./
COPY deploy/local/healthcheck.py ./deploy/local/healthcheck.py
CMD ["python", "training_worker.py"]

FROM base AS cooling
COPY cloud_controller.py ./
COPY deploy/shared/cooling.py ./cooling_service.py
COPY deploy/local/healthcheck.py ./deploy/local/healthcheck.py
CMD ["python", "cooling_service.py"]

FROM base AS web
USER root
RUN pip install --no-cache-dir tavily-cli==0.1.8
USER haunted
COPY *.py ./
COPY deploy/local/healthcheck.py ./deploy/local/healthcheck.py
COPY web ./web
COPY data ./data
COPY puzzles ./puzzles
COPY solutions ./solutions
ENV HOST=0.0.0.0 PORT=8080 GAME_DATA_DIR=/data/game
HEALTHCHECK --interval=5s --timeout=4s --retries=6 CMD python /app/deploy/local/healthcheck.py web
CMD ["python", "server.py"]
