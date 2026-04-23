"""Backward-compatible entrypoint: run the embedding-only API."""

from embedding.embed_server import app

__all__ = ["app"]
