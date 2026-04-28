from fastapi.testclient import TestClient
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
MAIN_ROOT = PROJECT_ROOT / "main"
if str(MAIN_ROOT) not in sys.path:
    sys.path.insert(0, str(MAIN_ROOT))
from app.main import app


client = TestClient(app)


def test_health_endpoint() -> None:
    response = client.get("/api/v1/health")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_ready_endpoint() -> None:
    response = client.get("/api/v1/ready")

    assert response.status_code == 200
    assert response.json()["status"] == "ready"
