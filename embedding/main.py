"""Backward-compatible entrypoint: run the embedding-only API."""

try:
    from embedding.embed_server import app
except ModuleNotFoundError:
    # Running from `embedding/` as `uvicorn main:app` (cwd on sys.path, no parent package).
    from embed_server import app

__all__ = ["app"]
