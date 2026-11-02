ARG SOMA_IMAGE=cr.eu-north1.nebius.cloud/e00qmygzhgqbsky5mh/soma-kubecon@sha256:de27c9a85b5241546e2170fafe00dd186cc51ad090d1d571f007c30f7e5dae06
FROM ${SOMA_IMAGE} AS soma
FROM cr.eu-north1.nebius.cloud/e00qmygzhgqbsky5mh/haunted-datacenter:posthog-v5 AS haunted
FROM pytorch/pytorch:2.8.0-cuda12.8-cudnn9-runtime
WORKDIR /app
COPY --from=soma /usr/local/bin/node /usr/local/bin/node
COPY --from=soma /app /opt/soma
COPY --from=haunted /usr/local/bin/nebius /usr/local/bin/nebius
COPY --from=haunted /app /app
RUN python -m pip install --no-cache-dir tavily-cli==0.1.8 transformers==4.57.1 peft==0.17.1 accelerate==1.10.1 safetensors==0.6.2 && \
    (id -u 1000 >/dev/null 2>&1 || useradd -m -u 1000 haunted) && \
    mkdir -p /home/haunted && chown 1000:1000 /home/haunted
COPY serverless.py local_runtime.py /app/
COPY training_worker.py /opt/training_worker.py
COPY deploy/shared /opt/shared
ENV PYTHONUNBUFFERED=1 TOKENIZERS_PARALLELISM=false OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 HF_HUB_DISABLE_TELEMETRY=1
EXPOSE 8000 8001 8080 8081 9000
ENTRYPOINT ["python", "/opt/shared/supervisor.py"]
