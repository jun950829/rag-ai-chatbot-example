FROM python:3.11-slim

WORKDIR /srv/embedding

COPY requirements-core.txt requirements-embed.txt install_deps.sh ./
RUN bash install_deps.sh cpu

COPY worker ./worker

CMD ["python", "-m", "worker.main"]
