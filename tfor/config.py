from __future__ import annotations

import os
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent.parent
DATABASE_PATH = Path(os.getenv("TFOR_DATABASE_PATH", BASE_DIR / "data" / "tfor.db"))
LOG_LEVEL = os.getenv("TFOR_LOG_LEVEL", "INFO").upper()
LOG_RETENTION_DAYS = 3
MAX_CONCURRENT_RULES = int(os.getenv("TFOR_MAX_CONCURRENT_RULES", "10"))
MAX_PENDING_RULES = int(os.getenv("TFOR_MAX_PENDING_RULES", "1000"))
MAX_CONCURRENT_COPIES = int(os.getenv("TFOR_MAX_CONCURRENT_COPIES", "4"))
MAX_CONCURRENT_COPIES_PER_ACCOUNT = int(os.getenv("TFOR_MAX_CONCURRENT_COPIES_PER_ACCOUNT", "2"))
INLINE_FLOOD_WAIT_SECONDS = int(os.getenv("TFOR_INLINE_FLOOD_WAIT_SECONDS", "60"))
MEDIA_TYPES = ("photo", "video", "document", "audio", "voice", "other")
