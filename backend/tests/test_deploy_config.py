"""Comprueba que la configuración de despliegue es coherente: es lo que más cuesta depurar en Vercel."""

import importlib.util
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[2]


def test_vercel_json_routes_api_to_the_function_and_bundles_the_backend():
    config = json.loads((ROOT / "vercel.json").read_text())
    assert config["outputDirectory"] == "frontend/dist"
    assert {"source": "/api/(.*)", "destination": "/api/index"} in config["rewrites"]
    fn = config["functions"]["api/index.py"]
    assert fn["includeFiles"] == "backend/app/**"
    assert fn["maxDuration"] >= 30, "debe superar el presupuesto de tiempo del servicio (BUILD_TIMEOUT_S)"
    assert (ROOT / "api" / "index.py").is_file()


def test_production_requirements_pin_what_the_app_imports():
    lines = [l.strip() for l in (ROOT / "requirements.txt").read_text().splitlines() if l.strip() and not l.startswith("#")]
    names = {re.split(r"[=<>]", l)[0].lower() for l in lines}
    assert {"fastapi", "httpx", "pydantic", "tzdata"} <= names
    assert "uvicorn" not in names and "pytest" not in names, "Vercel no los necesita"
    assert all("==" in l for l in lines if not l.startswith("tzdata"))


def test_function_entrypoint_works_with_only_the_files_vercel_bundles(tmp_path, monkeypatch):
    """Copia solo api/ y backend/app (lo que incluye vercel.json) y carga la función desde ahí."""
    shutil.copytree(ROOT / "api", tmp_path / "api")
    shutil.copytree(ROOT / "backend" / "app", tmp_path / "backend" / "app", ignore=shutil.ignore_patterns("__pycache__"))

    code = (
        "import sys; sys.path.insert(0, 'api'); "
        "import importlib.util as u; s = u.spec_from_file_location('entry', 'api/index.py'); "
        "m = u.module_from_spec(s); s.loader.exec_module(m); "
        "from fastapi.testclient import TestClient; "
        "c = TestClient(m.app); r = c.get('/api/overview'); "
        "print(r.status_code, r.headers['cache-control'], len(r.json()['locations']))"
    )
    result = subprocess.run(
        [sys.executable, "-I", "-c", code], cwd=tmp_path, capture_output=True, text=True,
        env={"DEMO_MODE": "true", "PATH": "", "SYSTEMROOT": ""},
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "200 public, max-age=60, s-maxage=600, stale-while-revalidate=3600 19"


def test_entrypoint_module_exposes_an_asgi_app(monkeypatch):
    monkeypatch.setenv("DEMO_MODE", "true")
    spec = importlib.util.spec_from_file_location("vercel_entry", ROOT / "api" / "index.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert TestClient(module.app).get("/api/health").json() == {"status": "ok"}


def test_workflows_do_not_reference_removed_endpoints():
    for wf in (ROOT / ".github" / "workflows").glob("*.yml"):
        text = wf.read_text()
        assert "/api/refresh" not in text and "REFRESH_TOKEN" not in text, wf.name
