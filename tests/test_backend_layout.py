from __future__ import annotations

import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_app_root_exposes_only_package_frontend_and_backend() -> None:
    app_root = PROJECT_ROOT / "app"
    direct_items = {
        path.name
        for path in app_root.iterdir()
        if path.name not in {"__pycache__"} and not path.name.endswith(".pyc")
    }

    assert direct_items == {"__init__.py", "backend", "frontend"}


def test_backend_contains_runtime_api_and_migrations() -> None:
    backend_root = PROJECT_ROOT / "app" / "backend"
    expected = {
        "cli.py",
        "config.py",
        "db.py",
        "main.py",
        "models.py",
        "realtime.py",
        "schemas.py",
        "api",
        "alembic.ini",
        "migrations",
    }

    assert expected <= {path.name for path in backend_root.iterdir()}
    assert not (PROJECT_ROOT / "alembic.ini").exists()
    assert not (PROJECT_ROOT / "alembic").exists()


def test_backend_cli_is_the_canonical_module_entrypoint() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "app.backend.cli", "--help"],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert "--role" in result.stdout


def test_powershell_launchers_use_backend_cli() -> None:
    for name in ("start_customer.ps1", "start_customer_service.ps1", "start_all.ps1"):
        content = (PROJECT_ROOT / "scripts" / name).read_text(encoding="utf-8")
        assert "app.backend.cli" in content
        assert "-m app.cli" not in content
