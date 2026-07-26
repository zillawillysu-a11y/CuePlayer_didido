"""Persistence unit tests."""

from __future__ import annotations

import pytest

from cueplayer.persistence.project_store import SchemaError, migrate_project_dict


def test_migrate_version_zero() -> None:
    data = migrate_project_dict({"id": "abc", "name": "測試", "songs": []}, from_version=0)
    assert data["schema_version"] == 1


def test_reject_future_schema() -> None:
    with pytest.raises(SchemaError):
        migrate_project_dict({"schema_version": 99, "id": "x", "name": "y"}, from_version=99)
