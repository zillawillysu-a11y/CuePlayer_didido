"""Internal product feature flags (easy to flip; no schema / persistence).

Experimental UI is hidden when ``ENABLE_EXPERIMENTAL_FEATURES`` is False.
Implementations, tests, domain models, and docs remain in the tree.
"""

from __future__ import annotations

# Sprint 8 — hide unfinished Tools entries (Align Anchors, MA Preflight menu).
# Set True to restore menu actions without other behavior changes.
ENABLE_EXPERIMENTAL_FEATURES: bool = False
