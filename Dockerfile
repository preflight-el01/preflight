# API image: FastAPI + job workers. Experiments run in sibling runner containers
# (PREFLIGHT_SANDBOX=docker, Docker socket mounted) or as subprocesses inside this one.
FROM python:3.13-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY engine engine
COPY server server
COPY dist dist
ENV PREFLIGHT_SANDBOX=subprocess PREFLIGHT_WORKERS=2
EXPOSE 8000
CMD ["uvicorn", "server.app:app", "--host", "0.0.0.0", "--port", "8000"]
