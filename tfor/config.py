from __future__ import annotations

import os
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent.parent
DATABASE_PATH = Path(os.getenv("TFOR_DATABASE_PATH", BASE_DIR / "data" / "tfor.db"))
LOG_LEVEL = os.getenv("TFOR_LOG_LEVEL", "INFO").upper()
LOG_RETENTION_DAYS = 3
MEDIA_TYPES = ("photo", "video", "document", "audio", "voice", "other")
