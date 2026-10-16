# Build from the nodeskclaw-meeting directory. CI and deployment explicitly target linux/amd64.
FROM --platform=linux/amd64 python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /app
COPY pyproject.toml ./
COPY app ./app
COPY alembic ./alembic
COPY alembic.ini ./
# Online dependency resolution is required for this RC. Freeze a uv.lock before production promotion.
RUN pip install --no-cache-dir . && useradd --uid 10001 --create-home meeting \
    && mkdir -p /data/private && chown -R meeting:meeting /data /app
USER 10001:10001
EXPOSE 8000
CMD ["uvicorn","app.main:create_app","--factory","--host","0.0.0.0","--port","8000","--no-access-log"]
