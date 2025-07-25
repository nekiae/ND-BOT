import asyncio
from typing import List
import re

TELEGRAM_MAX_MESSAGE_LENGTH = 4096

def split_long_message(text: str) -> List[str]:
    """
    Splits a long message into multiple smaller messages, ensuring that Markdown entities
    (*, _, `) are not broken across messages.

    Args:
        text: The text to split.

    Returns:
        A list of message chunks, each under the Telegram character limit.
    """
    if len(text) <= TELEGRAM_MAX_MESSAGE_LENGTH:
        return [text]

    parts = []
    current_pos = 0
    while current_pos < len(text):
        end_pos = current_pos + TELEGRAM_MAX_MESSAGE_LENGTH
        if end_pos >= len(text):
            parts.append(text[current_pos:])
            break

        # Find the best possible split position by searching backwards
        # Prefer splitting at paragraph breaks, then line breaks, then spaces.
        split_pos = text.rfind('\n\n', current_pos, end_pos)
        if split_pos == -1:
            split_pos = text.rfind('\n', current_pos, end_pos)
        if split_pos == -1:
            split_pos = text.rfind(' ', current_pos, end_pos)
        if split_pos == -1:
            split_pos = end_pos # Hard split if no suitable character found

        # Ensure we don't have unclosed markdown entities
        chunk = text[current_pos:split_pos]
        for char in ['*', '_', '`']:
            if chunk.count(char) % 2 != 0:
                # Unclosed entity found, try to move the split before it
                last_entity_pos = chunk.rfind(char)
                if last_entity_pos != -1:
                    # We move the split position to before this entity
                    split_pos = current_pos + last_entity_pos
                    break # Recalculating chunk is complex, just split here
        
        # If the split position was moved back significantly, re-evaluate chunk
        chunk = text[current_pos:split_pos]
        parts.append(chunk)
        current_pos = split_pos

    # Clean up any empty parts that might have been created
    return [p.strip() for p in parts if p.strip()]

def sanitize_html_for_telegram(text: str) -> str:
    """Converts common Markdown styling (bold/italic) to Telegram HTML and ensures tags are balanced.

    1. Replaces **bold** with <b>bold</b>
    2. Replaces *italic* with <i>italic</i> while ignoring bullet-list markers (\"* \")
    3. Adds any missing closing tags so Telegram does not raise parse errors.
    """
    # --- Markdown → HTML conversion --- #
    # Bold: **text** → <b>text</b>
    text = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", text, flags=re.DOTALL)

    # Italic: *text* → <i>text</i>
    # We deliberately ignore the pattern \"* \" (bullet list) by ensuring the first * is not
    # followed by whitespace.
    text = re.sub(r"(?<!\*)\*(?!\s)(.+?)(?<!\s)\*(?!\*)", r"<i>\1</i>", text, flags=re.DOTALL)

    # --- Balance HTML tags to avoid Telegram \"can't parse entities\" errors --- #
    for tag in ("b", "i"):
        opens = len(re.findall(f"<{tag}>", text))
        closes = len(re.findall(f"</{tag}>", text))
        if opens > closes:
            text += "</" + tag + ">" * (opens - closes)
        elif closes > opens:
            # Remove extra closing tags from the end if they outnumber openings (rare but safe-guard)
            extra = closes - opens
            text = text[::-1].replace(f">/{tag}<"[::-1], "", extra)[::-1]
    return text
