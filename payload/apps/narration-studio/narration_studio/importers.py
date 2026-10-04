from __future__ import annotations

import shutil
from pathlib import Path


TEXT_EXTENSIONS = {".txt", ".md", ".markdown"}
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".bmp"}


def read_document(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix in TEXT_EXTENSIONS:
        return path.read_text(encoding="utf-8-sig", errors="replace")
    if suffix == ".pdf":
        try:
            from pypdf import PdfReader
        except ImportError as exc:
            raise RuntimeError("PDF import needs pypdf. Install the Narration Studio document extras.") from exc
        return "\n\n".join(page.extract_text() or "" for page in PdfReader(str(path)).pages)
    if suffix == ".docx":
        try:
            from docx import Document
        except ImportError as exc:
            raise RuntimeError("DOCX import needs python-docx. Install the Narration Studio document extras.") from exc
        return "\n".join(paragraph.text for paragraph in Document(str(path)).paragraphs)
    if suffix == ".epub":
        try:
            from bs4 import BeautifulSoup
            from ebooklib import ITEM_DOCUMENT, epub
        except ImportError as exc:
            raise RuntimeError("EPUB import needs EbookLib and beautifulsoup4.") from exc
        book = epub.read_epub(str(path))
        return "\n\n".join(BeautifulSoup(item.get_content(), "html.parser").get_text(" ", strip=True)
                             for item in book.get_items_of_type(ITEM_DOCUMENT))
    raise ValueError(f"Unsupported document type: {suffix or '(none)'}")


def copy_source(path: Path, sources_folder: Path) -> Path:
    sources_folder.mkdir(parents=True, exist_ok=True)
    destination = sources_folder / path.name
    counter = 2
    while destination.exists() and destination.resolve() != path.resolve():
        destination = sources_folder / f"{path.stem}_{counter}{path.suffix}"
        counter += 1
    if destination.resolve() != path.resolve():
        shutil.copy2(path, destination)
    return destination
