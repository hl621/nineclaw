"""Pydantic schemas for the file-based Skill registry.

A "skill" is a directory inside ``settings.skills_storage_path`` that
contains a ``SKILL.md`` file. ``SKILL.md`` starts with a YAML frontmatter
block (delimited by ``---``) carrying the skill's metadata. The body of
``SKILL.md`` is the prose used by agents at runtime.

Example ``SKILL.md``::

    ---
    name: markdown-viewer
    description: "Render rich diagrams via Markdown..."
    version: 1.0.0
    author: Ekko
    license: MIT
    platforms: [linux, macos, windows]
    metadata:
      hermes:
        tags: [markdown, diagrams]
    ---

    # Markdown Viewer
    ...
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class SkillResponse(BaseModel):
    """One entry in ``GET /skills``.

    ``id`` is just the directory name on disk — the filesystem is the
    source of truth, so we don't allocate UUIDs. Names are matched
    case-sensitively to be portable across Linux containers and macOS
    development hosts.
    """

    id: str = Field(description="Directory name on disk; doubles as the URL slug.")
    name: str = Field(description="Human-readable name from SKILL.md frontmatter.")
    description: str = Field(default="")
    author: str = Field(default="")
    license: str = Field(default="")
    platforms: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(
        default_factory=dict,
        description="Pass-through for any extra frontmatter keys.",
    )
    file_count: int = Field(default=0)
    size_bytes: int = Field(default=0)
    updated_at: datetime
    has_readme: bool = Field(
        default=False,
        description="True if a README.md exists alongside SKILL.md.",
    )


class SkillCreateRequest(BaseModel):
    """Body for ``POST /skills`` — create an empty skill folder on disk."""

    name: str = Field(..., min_length=1, description="Human-readable skill name.")
    description: str = Field(..., min_length=1, description="Short skill summary.")


class SkillDetailResponse(SkillResponse):
    """Same as ``SkillResponse`` plus the raw SKILL.md body."""

    skill_md: str = Field(default="", description="Full SKILL.md contents.")
    files: list[str] = Field(
        default_factory=list,
        description="Relative paths of every file in the skill folder.",
    )
