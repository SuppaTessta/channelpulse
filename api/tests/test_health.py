from fastapi.testclient import TestClient

from app.main import app, db_conninfo


def test_health_honours_postgres_env_and_survives_db_down(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("POSTGRES_HOST", "127.0.0.1")
    monkeypatch.setenv("POSTGRES_PORT", "1")  # nothing listens here

    assert "port=1" in db_conninfo()
    response = TestClient(app).get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "db": "unreachable"}
