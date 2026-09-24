FROM python:3.12-slim

WORKDIR /srv
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app ./app
COPY sql ./sql

RUN useradd --system --no-create-home api
USER api

EXPOSE 8000
# Hosts like Render pass the port in $PORT; locally and in compose it's 8000.
CMD ["sh", "-c", "exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
