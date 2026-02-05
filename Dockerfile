# Agent Swarm Protocol - FastAPI Handler
# Multi-stage build for minimal production image

FROM python:3.12-slim AS builder

WORKDIR /build

RUN pip install --no-cache-dir hatchling

COPY pyproject.toml .
COPY src/ src/

RUN pip wheel --no-cache-dir --wheel-dir /build/wheels .


FROM python:3.12-slim AS runtime

LABEL org.opencontainers.image.title="Agent Swarm Protocol Handler"
LABEL org.opencontainers.image.description="FastAPI handler for Agent Swarm Protocol"
LABEL org.opencontainers.image.version="0.1.0"

RUN groupadd --gid 1000 swarm \
    && useradd --uid 1000 --gid swarm --shell /bin/bash --create-home swarm

WORKDIR /app

COPY --from=builder /build/wheels /wheels
RUN pip install --no-cache-dir /wheels/*.whl && rm -rf /wheels

COPY src/ src/

RUN mkdir -p /app/data && chown -R swarm:swarm /app

USER swarm

ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD python -c "import httpx; httpx.get('http://localhost:8080/swarm/health', timeout=5).raise_for_status()"

CMD ["python", "-m", "uvicorn", "src.server.app:create_app", "--factory", \
     "--host", "0.0.0.0", "--port", "8080", "--no-access-log"]
