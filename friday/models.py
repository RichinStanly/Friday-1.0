from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class Conversation:
    id: str
    title: str
    model: str
    created_at: str
    updated_at: str
    summary: str = ""
    web_enabled: bool = False
    memory_enabled: bool = True
    incognito: bool = False
    pinned: bool = False
    archived: bool = False


@dataclass(slots=True)
class Message:
    id: str
    conversation_id: str
    role: str
    content: str
    created_at: str
    metadata: str = "{}"


@dataclass(slots=True)
class LocalModel:
    name: str
    size_bytes: int = 0
    modified_at: str = ""
    details: str = ""
    display_name: str = ""
    capability: str = ""

    @property
    def size_label(self) -> str:
        if not self.size_bytes:
            return "Available locally"
        return f"{self.size_bytes / 1_073_741_824:.1f} GB"
