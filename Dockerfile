FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir --default-timeout=1000 --retries 10 -r /app/requirements.txt

COPY app /app/app
COPY pipeline /app/pipeline
COPY dashboard /app/dashboard
COPY config /app/config
COPY sample_data /app/sample_data
COPY models /app/models
COPY docs /app/docs
COPY scripts /app/scripts
COPY README.md /app/README.md

COPY ["Brigade_Bangalore_10_April_26 (1)bc6219c.csv", "/app/Brigade_Bangalore_10_April_26 (1)bc6219c.csv"]
COPY ["POS - sample transactionsb1e826f.csv", "/app/POS - sample transactionsb1e826f.csv"]
COPY ["sample_eventsbe42122.jsonl", "/app/sample_eventsbe42122.jsonl"]

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
