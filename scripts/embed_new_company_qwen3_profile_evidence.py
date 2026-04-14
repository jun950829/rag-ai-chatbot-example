from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

# Make `embedding` / `app` imports work when running as `python scripts/...py`
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from embedding.pipeline import (  # noqa: E402
    DEFAULT_EMBEDDING_MODEL_ID,
    EVIDENCE_TABLE_ENG,
    EVIDENCE_TABLE_KOR,
    PROFILE_TABLE_ENG,
    PROFILE_TABLE_KOR,
    _build_embeddings,
    _fetch_new_company_rows,
    _resolve_device,
    _upsert_embeddings,
)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Embed new_company rows and upsert into the four Qwen3 0.6B embedding tables (same path as embedding web app)."
    )
    parser.add_argument(
        "--model",
        default=os.environ.get("EMBEDDING_MODEL_ID", DEFAULT_EMBEDDING_MODEL_ID),
        help="HuggingFace model id (default: Qwen/Qwen3-Embedding-0.6B)",
    )
    parser.add_argument("--limit", type=int, default=None, help="Limit number of new_company rows")
    parser.add_argument("--batch-size", type=int, default=int(os.environ.get("EMBEDDING_BATCH_SIZE", "8")))
    parser.add_argument(
        "--entity-batch-size",
        type=int,
        default=int(os.environ.get("EMBEDDING_ENTITY_BATCH_SIZE", "64")),
        help="Rows of new_company processed per GPU/model batch (default: 64)",
    )
    parser.add_argument(
        "--device",
        default=os.environ.get("EMBEDDING_DEVICE", "mps"),
        help="Device (mps / cpu / cuda); mps falls back to cpu if unavailable",
    )
    parser.add_argument("--evidence-max-chars", type=int, default=1200)
    parser.add_argument("--evidence-overlap", type=int, default=150)

    args = parser.parse_args()

    rows = _fetch_new_company_rows(args.limit)
    if not rows:
        raise SystemExit("new_company has no rows to embed.")

    resolved_device = _resolve_device(args.device)
    results = _build_embeddings(
        rows,
        model_id=args.model,
        batch_size=args.batch_size,
        entity_batch_size=args.entity_batch_size,
        device=resolved_device,
        max_chars=args.evidence_max_chars,
        overlap=args.evidence_overlap,
        progress=None,
    )
    counts = _upsert_embeddings(results, progress=None)

    print("Upserted rows:")
    for key in (PROFILE_TABLE_KOR, PROFILE_TABLE_ENG, EVIDENCE_TABLE_KOR, EVIDENCE_TABLE_ENG):
        print(f"  {key}: {counts.get(key, 0)}")
    print(f"  total: {sum(counts.values())}")


if __name__ == "__main__":
    main()
