"""Punto de entrada de Vercel: expone la app FastAPI como función serverless.

El código vive en backend/app (ahí también corren los tests). vercel.json lo incluye en la función
con `includeFiles`, y aquí se agrega backend/ al path de importación.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from app.main import create_app  # noqa: E402

app = create_app()
