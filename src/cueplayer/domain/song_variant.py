"""Song media variants (domain only).

A ``Song`` may own multiple ``SongVariant`` packages. Marks stay on the song
timeline; playback (later) uses one selected variant at a time.

This module must stay free of Qt, JSON/persistence, and AudioEngine.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal, Mapping
from uuid import uuid4

VariantKind = Literal["audio", "video", "ltc", "click"]

_VALID_KINDS: frozenset[str] = frozenset({"audio", "video", "ltc", "click"})


def coerce_variant_kind(value: object, *, default: VariantKind = "audio") -> VariantKind:
    """Normalize a variant kind string; unknown values become ``default``."""
    raw = str(value or "").strip().lower()
    if raw in _VALID_KINDS:
        return raw  # type: ignore[return-value]
    return default


def _new_variant_id() -> str:
    return str(uuid4())


@dataclass
class SongVariant:
    """One switchable media package belonging to a ``Song``.

    Field notes
    -----------
    id
        Why: stable identity for selection and future undo/persistence.
        Future: schema v2 ``selected_variant_id``, Remote ops.
        Required.

    name
        Why: operator label ("Old mix", "v2") independent of file name.
        Future: UI picker / setlist badges.
        Required (may be empty string only if caller allows; ``create`` trims).

    kind
        Why: distinguishes audio bed vs future video/LTC/click packages.
        Future: multi-media bags or parallel kinds without a second clock.
        Required (default ``audio``).

    path
        Why: filesystem location of this variant's primary media file.
        Future: Unicode paths, bundle/relink scanners.
        Required (Path; may point at a missing file until relink).

    anchor_offset
        Why: shift media vs the song cue timeline (Align Anchors later).
        Future: Align Anchors / compare without moving marks.
        Optional (default ``0.0`` seconds).

    enabled
        Why: soft-disable a mix without deleting it.
        Future: UI mute-in-list; selection fallbacks skip disabled.
        Optional (default ``True``).

    metadata
        Why: extensible string bag without schema churn (notes, probe hints).
        Future: BPM probe cache keys, user tags — not MA XML labels.
        Optional (default empty mapping).
    """

    id: str
    name: str
    kind: VariantKind = "audio"
    path: Path = field(default_factory=Path)
    anchor_offset: float = 0.0
    enabled: bool = True
    metadata: dict[str, str] = field(default_factory=dict)

    @classmethod
    def create(
        cls,
        name: str,
        path: Path | str,
        *,
        kind: VariantKind | str = "audio",
        anchor_offset: float = 0.0,
        enabled: bool = True,
        metadata: Mapping[str, Any] | None = None,
        id: str | None = None,
    ) -> SongVariant:
        """Build a variant with a fresh id (unless ``id`` is provided)."""
        meta: dict[str, str] = {}
        if metadata:
            meta = {str(k): str(v) for k, v in metadata.items()}
        return cls(
            id=id or _new_variant_id(),
            name=str(name).strip() or "Variant",
            kind=coerce_variant_kind(kind),
            path=Path(path),
            anchor_offset=float(anchor_offset),
            enabled=bool(enabled),
            metadata=meta,
        )

    def copy_with_new_id(self) -> SongVariant:
        """Duplicate for song copy/undo; preserves fields, new ``id``."""
        return SongVariant(
            id=_new_variant_id(),
            name=self.name,
            kind=self.kind,
            path=Path(self.path),
            anchor_offset=float(self.anchor_offset),
            enabled=bool(self.enabled),
            metadata=dict(self.metadata),
        )

    @property
    def is_audio(self) -> bool:
        return self.kind == "audio"

    def has_resolvable_path(self) -> bool:
        """True when ``path`` is a non-empty, non-dot path string.

        Does not check disk existence (relink is a later concern).
        """
        text = str(self.path).strip()
        return bool(text) and text not in (".", "./")
