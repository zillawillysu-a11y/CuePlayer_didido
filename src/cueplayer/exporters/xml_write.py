"""XML helpers shared by exporters."""

from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path
from uuid import uuid4


MA2_NS = "http://schemas.malighting.de/grandma2/xml/MA"
MA2_XSI = "http://www.w3.org/2001/XMLSchema-instance"


def ma3_guid() -> str:
    raw = uuid4().hex.upper()
    parts = [raw[i : i + 2] for i in range(0, 32, 2)]
    return " ".join(parts)


def indent_xml(elem: ET.Element, space: str = "    ") -> None:
    ET.indent(elem, space=space)


def write_xml(
    root: ET.Element,
    path: Path,
    *,
    encoding: str = "UTF-8",
    xml_declaration: bool = True,
    default_namespace: str | None = None,
    stylesheet_hrefs: list[str] | None = None,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if default_namespace:
        ET.register_namespace("", default_namespace)
    indent_xml(root)
    tree = ET.ElementTree(root)

    # ElementTree doesn't make stylesheet PIs easy; write manually for MA2 parity.
    payload = ET.tostring(root, encoding="unicode")
    lines = ['<?xml version="1.0" encoding="utf-8"?>']
    for href in stylesheet_hrefs or []:
        lines.append(f'<?xml-stylesheet type="text/xsl" href="{href}"?>')
    lines.append(payload)
    text = "\n".join(lines) + "\n"
    path.write_text(text, encoding=encoding)


def seconds_to_ma2_frames(seconds: float, fps: float) -> int:
    return max(0, int(round(seconds * fps)))
