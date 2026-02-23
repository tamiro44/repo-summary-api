"""Assembles the LLM context string from scored repository files.

Includes files in priority order (lowest score first) until the character
budget is exhausted.  Individual files are truncated to a per-file cap so
that a single large file cannot consume the entire budget.
"""

from __future__ import annotations

from models.schemas import RepoFile


def build_context(
    files: list[RepoFile],
    budget: int,
    per_file_max: int,
) -> str:
    """Build a context string from downloaded files within *budget* chars.

    Files must already be sorted by score (ascending) and have their
    ``content`` field populated.

    Returns the assembled context string ready for prompt injection.
    """
    sections: list[str] = []
    used = 0

    for f in files:
        if f.content is None:
            continue

        content = f.content
        if len(content) > per_file_max:
            content = content[:per_file_max] + "\n... [truncated]"

        header = f"### {f.path}\n"
        section = header + "```\n" + content + "\n```\n"
        section_len = len(section)

        if used + section_len > budget:
            remaining = budget - used
            if remaining > len(header) + 50:
                # Fit a partial section
                available = remaining - len(header) - 20
                section = (
                    header + "```\n" + content[:available] + "\n... [truncated]\n```\n"
                )
                sections.append(section)
            break

        sections.append(section)
        used += section_len

    return "\n".join(sections)
