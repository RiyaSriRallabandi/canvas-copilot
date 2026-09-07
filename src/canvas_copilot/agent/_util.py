"""Small helpers for working with LangChain message objects."""

from __future__ import annotations

from langchain_core.messages import BaseMessage


def message_text(message: BaseMessage) -> str:
    """The message's text content (``.content`` may be a str or a list of parts)."""
    content = message.content
    if isinstance(content, str):
        return content
    return " ".join(part for part in content if isinstance(part, str))
