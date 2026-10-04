from __future__ import annotations

import re


def clean_spoken_text(text: str, skip_symbols: bool) -> str:
    if not skip_symbols:
        return text.strip()
    cleaned = "".join(character if character.isalnum() or character.isspace() or character in "'’" else " "
                      for character in text)
    return re.sub(r"\s+", " ", cleaned).strip()


def text_chunks_with_ranges(text: str, limit: int = 450) -> list[tuple[int, int, str]]:
    if limit < 40:
        raise ValueError("Text reader chunk limit must be at least 40 characters.")
    chunks: list[tuple[int, int, str]] = []
    position = 0
    while position < len(text):
        while position < len(text) and text[position].isspace():
            position += 1
        if position >= len(text):
            break
        end = min(len(text), position + limit)
        window = text[position:end]
        endings = [match.end() for match in re.finditer(r"[.!?…][\"'”’)]*(?:\s+|$)|\n+", window)]
        useful = [offset for offset in endings if 10 <= offset < len(window)]
        if useful:
            end = position + useful[0]
        elif end < len(text):
            space = window.rfind(" ", limit // 3)
            if space > 0:
                end = position + space + 1
        raw = text[position:end]
        leading = len(raw) - len(raw.lstrip())
        trailing = len(raw.rstrip())
        start, actual_end = position + leading, position + trailing
        if actual_end > start:
            chunks.append((start, actual_end, text[start:actual_end]))
        position = max(end, position + 1)
    return chunks

