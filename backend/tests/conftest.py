import pytest

from app import db


@pytest.fixture
async def database(tmp_path):
    await db.connect(tmp_path / "test.db")
    yield db
    await db.close()
