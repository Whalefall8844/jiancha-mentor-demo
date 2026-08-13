from __future__ import annotations

from hashlib import sha256
from pathlib import Path
from uuid import uuid4


BACKEND_DIR = Path(__file__).resolve().parent.parent
CONTROLLED_DOCUMENTS_DIR = BACKEND_DIR / "uploads" / "controlled-documents"


def save_controlled_document_file(
    *,
    project_id: str,
    site_id: str,
    file_name: str,
    content: bytes,
) -> dict[str, str]:
    safe_name = Path(file_name or "controlled-document").name
    folder = CONTROLLED_DOCUMENTS_DIR / project_id / (site_id or "project")
    folder.mkdir(parents=True, exist_ok=True)
    stored_file = folder / f"{uuid4().hex}_{safe_name}"
    stored_file.write_bytes(content)
    return {
        "source_file_name": safe_name,
        "stored_path": str(stored_file),
        "content_hash": sha256(content).hexdigest(),
    }


def get_stored_controlled_document(stored_path: str) -> Path | None:
    path = Path(stored_path)
    return path if path.exists() and path.is_file() else None
