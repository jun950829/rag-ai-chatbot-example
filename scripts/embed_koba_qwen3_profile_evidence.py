#!/usr/bin/env python3
"""Embed `koba_exhibitor` or `koba_exhibit_item` rows into KOBA pgvector tables (same path as embed_server)."""

from __future__ import annotations

import argparse
import os
import sys

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
MAIN_ROOT = os.path.join(PROJECT_ROOT, "main")
sys.path.insert(0, MAIN_ROOT)
sys.path.insert(1, PROJECT_ROOT)

from app.rag.pipeline import (  # noqa: E402
    DEFAULT_EMBEDDING_MODEL_ID,
    _build_embeddings,
    _fetch_koba_exhibit_item_rows,
    _fetch_koba_exhibitor_rows,
    _upsert_embeddings,
)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Embed KOBA catalog rows into Qwen3 KOBA embedding tables."
    )
    parser.add_argument(
        "--entity",
        choices=("exhibitor", "exhibit_item"),
        default="exhibitor",
        help="Which source table to embed.",
    )
    parser.add_argument("--model-id", default=DEFAULT_EMBEDDING_MODEL_ID)
    parser.add_argument("--device", default=None)
    parser.add_argument("--batch-size", type=int, default=8)
    parser.add_argument("--entity-batch-size", type=int, default=64)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--evidence-max-chars", type=int, default=1200)
    parser.add_argument("--evidence-overlap", type=int, default=150)
    args = parser.parse_args()

    rows = (
        _fetch_koba_exhibitor_rows(args.limit)
        if args.entity == "exhibitor"
        else _fetch_koba_exhibit_item_rows(args.limit)
    )
    if not rows:
        raise SystemExit(f"No rows in koba_{'exhibitor' if args.entity == 'exhibitor' else 'exhibit_item'} to embed.")

    results = _build_embeddings(
        rows,
        model_id=args.model_id,
        batch_size=args.batch_size,
        entity_batch_size=args.entity_batch_size,
        device=args.device,
        max_chars=args.evidence_max_chars,
        overlap=args.evidence_overlap,
        koba_entity=args.entity,
    )
    counts = _upsert_embeddings(results, model_id=args.model_id, koba_entity=args.entity)
    print("done", counts)


if __name__ == "__main__":
    main()
