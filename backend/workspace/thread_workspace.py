# -*- coding: utf-8 -*-
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path


@dataclass(frozen=True)
class WorkspaceNote:
    thread_id: str
    path: Path
    appended_chars: int


class ThreadWorkspace:
    def __init__(self, *, root: str | Path) -> None:
        self.root = Path(root)

    def _thread_dir(self, thread_id: str) -> Path:
        cleaned = re.sub(r"[^A-Za-z0-9_.-]+", "_", str(thread_id or "").strip())[:96].strip("._")
        if not cleaned:
            cleaned = "anonymous"
        path = (self.root / cleaned).resolve()
        root = self.root.resolve()
        if root not in path.parents and path != root:
            raise ValueError("thread workspace path escaped root")
        return path

    def append_note(self, *, thread_id: str, content: str) -> WorkspaceNote:
        thread_dir = self._thread_dir(thread_id)
        thread_dir.mkdir(parents=True, exist_ok=True)
        note_path = thread_dir / "notes.md"
        timestamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
        text = str(content or "").strip()
        block = f"\n## {timestamp}\n\n{text}\n" if text else f"\n## {timestamp}\n\n(empty note)\n"
        with note_path.open("a", encoding="utf-8") as handle:
            handle.write(block)
        return WorkspaceNote(thread_id=str(thread_id or ""), path=note_path, appended_chars=len(block))

    def read_notes(self, thread_id: str) -> str:
        note_path = self._thread_dir(thread_id) / "notes.md"
        if not note_path.exists():
            return ""
        return note_path.read_text(encoding="utf-8")
