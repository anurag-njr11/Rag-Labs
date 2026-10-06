import pytest

from app import db, vault


@pytest.fixture(autouse=True)
def _isolated_secret_key(tmp_path, monkeypatch):
    """Never read or create the developer's real secret key file."""
    monkeypatch.delenv("RAGLABS_SECRET_KEY", raising=False)
    monkeypatch.setenv("RAGLABS_SECRET_KEY_FILE", str(tmp_path / "secret.key"))
    vault.reset_key_cache()
    yield
    vault.reset_key_cache()


@pytest.fixture
async def database(tmp_path):
    await db.connect(tmp_path / "test.db")
    yield db
    await db.close()
