"""Inspect and compare exported MA XML fixtures (no generation yet)."""

from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path


def load_xml_root(path: Path) -> ET.Element:
    tree = ET.parse(path)
    root = tree.getroot()
    return root


def xml_tag_local(tag: str) -> str:
    if "}" in tag:
        return tag.rsplit("}", 1)[-1]
    return tag


def collect_tag_names(root: ET.Element) -> set[str]:
    return {xml_tag_local(el.tag) for el in root.iter()}


def require_tags(root: ET.Element, required: set[str]) -> list[str]:
    present = collect_tag_names(root)
    return sorted(required - present)
