FROM python:3.10-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/workspace/apps/backend/.venv/bin:$PATH"

WORKDIR /workspace/apps/backend

RUN apt-get update \
    && apt-get install --no-install-recommends -y build-essential libsnappy-dev \
    && rm -rf /var/lib/apt/lists/* \
    && pip install --no-cache-dir uv==0.12.5

COPY apps/backend/pyproject.toml apps/backend/uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

COPY apps/backend/ ./
COPY config/project.template.json /workspace/config/project.json
COPY config/user.project.template.json /workspace/config/user.project.json
RUN uv sync --frozen --no-dev
RUN mkdir -p /workspace/apps/backend/var

EXPOSE 8000

CMD ["uvicorn", "super_ai.api.app:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000"]
