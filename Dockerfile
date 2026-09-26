FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
RUN mkdir -p /app/data
EXPOSE 8000
CMD ["sh", "-c", "uvicorn tfor.main:app --host ${TFOR_HOST:-0.0.0.0} --port ${TFOR_PORT:-8000}"]
