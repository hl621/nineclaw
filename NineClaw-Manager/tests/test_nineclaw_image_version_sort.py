"""Unit tests for NineClaw image version sorting."""

from __future__ import annotations

from app.services.docker_service import (
    _normalize_nineclaw_image_versions,
    _version_sort_key,
)


def test_version_sort_key_numeric_not_lexicographic():
    tags = ["v2026.7.7.2", "v2026.7.20", "v2026.7.1", "v2026.6.19"]
    ordered = sorted(tags, key=_version_sort_key, reverse=True)
    assert ordered == ["v2026.7.20", "v2026.7.7.2", "v2026.7.1", "v2026.6.19"]


def test_normalize_sorts_by_semantic_version_not_created_or_string():
    # Intentionally give the lower version a newer Created timestamp and a
    # lexicographically-greater image string, to prove version wins.
    raw = [
        {
            "Created": 200,
            "RepoTags": ["nineclaw:v2026.7.7.2"],
        },
        {
            "Created": 100,
            "RepoTags": ["nineclaw:v2026.7.20"],
        },
        {
            "Created": 300,
            "RepoTags": ["nineclaw:v2026.7.1"],
        },
        {
            "Created": 50,
            "RepoTags": ["nineclaw:v2026.6.19"],
        },
    ]
    versions = _normalize_nineclaw_image_versions(raw, "nineclaw")
    assert [item["tag"] for item in versions] == [
        "v2026.7.20",
        "v2026.7.7.2",
        "v2026.7.1",
        "v2026.6.19",
    ]
