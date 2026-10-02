"""The documentation, served to the page so it can be read in the app (the "Docs" links)."""

from __future__ import annotations

import re

from fastapi import APIRouter, HTTPException

from app import paths

router = APIRouter(prefix="/api/docs", tags=["docs"])

#: The guides come first, in this order; any other .md in the docs folder follows.
FIRST = ["getting_started", "indicators", "drawings"]


def _title(text: str, fallback: str) -> str:
    match = re.search(r"^#\s+(.+?)\s*$", text, flags=re.MULTILINE)
    return match.group(1) if match else fallback


def _documents() -> dict[str, str]:
    """``{id: file text}`` for every document in the docs folder."""
    folder = paths.docs_dir()
    found: dict[str, str] = {}
    if folder.is_dir():
        for file in sorted(folder.glob("*.md")):
            found[file.stem.lower()] = file.read_text(encoding="utf-8")
    return found


@router.get("")
def list_docs() -> list[dict]:
    docs = _documents()
    ids = [d for d in FIRST if d in docs] + [d for d in docs if d not in FIRST]
    return [{"id": d, "title": _title(docs[d], d.title())} for d in ids]


@router.get("/{doc_id}")
def read_doc(doc_id: str) -> dict:
    docs = _documents()
    key = doc_id.lower()
    if key not in docs:
        raise HTTPException(status_code=404, detail=f"no document {doc_id}")
    return {"id": key, "title": _title(docs[key], key.title()), "markdown": docs[key]}
