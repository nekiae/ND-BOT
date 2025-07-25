import asyncio
import re
from typing import List

TELEGRAM_MAX_MESSAGE_LENGTH = 4096

def sanitize_html_for_telegram(text: str) -> str:
    """
    Converts specific Markdown patterns to Telegram-compatible HTML tags and cleans the output.
    - Converts **bold** to <b>bold</b>
    - Converts *italic* to <i>italic</i>
    - Ignores asterisks used for lists (e.g., "* item").
    - Balances <b> and <i> tags to prevent Telegram parsing errors.
    """
    # Convert **text** to <b>text</b>, but not if it's part of a list item like '* '
    text = re.sub(r'\*\*([^\*\n][^\*]*?)\*\*', r'<b>\1</b>', text)
    # Convert *text* to <i>text</i>, but not if it's a list marker
    text = re.sub(r'(?<!\*)\*([^\*\n][^\*]*?)\*(?!\*)', r'<i>\1</i>', text)

    # Balance <b> tags
    open_b = text.count('<b>')
    close_b = text.count('</b>')
    if open_b > close_b:
        text += '</b>' * (open_b - close_b)
    elif close_b > open_b:
        # This is trickier, we'll remove the last closing tags
        for _ in range(close_b - open_b):
            last_pos = text.rfind('</b>')
            if last_pos != -1:
                text = text[:last_pos] + text[last_pos+4:]

    # Balance <i> tags
    open_i = text.count('<i>')
    close_i = text.count('</i>')
    if open_i > close_i:
        text += '</i>' * (open_i - close_i)
    elif close_i > open_i:
        for _ in range(close_i - open_i):
            last_pos = text.rfind('</i>')
            if last_pos != -1:
                text = text[:last_pos] + text[last_pos+4:]

    return text


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
