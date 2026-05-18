from __future__ import annotations

import uvicorn

from worker.embed_api import app


def main() -> None:
    uvicorn.run(app, host="0.0.0.0", port=9000, log_level="info")


if __name__ == "__main__":
    main()

