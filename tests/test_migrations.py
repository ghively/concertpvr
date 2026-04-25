import subprocess
import sys


def test_migration_upgrade_then_downgrade(tmp_path, monkeypatch):
    monkeypatch.setenv("CPVR_DATA_DIR", str(tmp_path))

    # upgrade to head
    r = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        capture_output=True,
        text=True,
    )
    assert r.returncode == 0, r.stderr

    db = tmp_path / "metadata.db"
    assert db.exists()

    # downgrade
    r = subprocess.run(
        [sys.executable, "-m", "alembic", "downgrade", "base"],
        capture_output=True,
        text=True,
    )
    assert r.returncode == 0, r.stderr
