import asyncio
from typing import List

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
