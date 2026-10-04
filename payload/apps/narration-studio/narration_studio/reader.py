from __future__ import annotations

import re


def text_chunks_with_ranges(text: str, limit: int = 450) -> list[tuple[int, int, str]]:
    """Split long text for TTS while retaining offsets for UI highlighting."""
    if limit < 40:
        raise ValueError("Text reader chunk limit must be at least 40 characters.")
    chunks: list[tuple[int, int, str]] = []
    position = 0
    length = len(text)
    while position < length:
        while position < length and text[position].isspace():
            position += 1
        if position >= length:
            break
        end = min(length, position + limit)
        window = text[position:end]
        sentence_ends = [match.end() for match in re.finditer(r"[.!?…][\"'”’)]*(?:\s+|$)|\n+", window)]
        useful = [offset for offset in sentence_ends if offset >= 10 and offset < len(window)]
        if useful:
            end = position + useful[0]
        elif end < length:
            space = window.rfind(" ", limit // 3)
            if space > 0:
                end = position + space + 1
        raw = text[position:end]
        leading = len(raw) - len(raw.lstrip())
        trailing = len(raw.rstrip())
        start = position + leading
        actual_end = position + trailing
        spoken = text[start:actual_end]
        if spoken:
            chunks.append((start, actual_end, spoken))
        position = max(end, position + 1)
    return chunks
