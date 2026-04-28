FROM python:3.11-slim

WORKDIR /srv/embedding

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY worker ./worker

CMD ["python", "-m", "worker.main"]
