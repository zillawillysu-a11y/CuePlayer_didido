"""Drag-and-drop MIME types shared across otherwise-unrelated UI widgets.

Kept in its own module (no PySide6 imports needed) so both the Setlist
sidebar (``main_window.SetlistWidget``) and the MA Export Queue
(``show_patch_page.ExportQueueList``) can agree on a payload format without
importing each other.
"""

from __future__ import annotations

# Newline-joined song ids (UTF-8). Producers: SetlistWidget (song rows and
# whole-folder drags). Consumers: ExportQueueList.
EXPORT_SONG_IDS_MIME = "application/x-cueplayer-export-song-ids"
