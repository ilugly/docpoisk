FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /srv

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY app ./app

# Какой сервис запускать (ingest или chat) задаётся в docker-compose.yml
CMD ["uvicorn", "app.chat_service:app", "--host", "0.0.0.0", "--port", "8000"]
