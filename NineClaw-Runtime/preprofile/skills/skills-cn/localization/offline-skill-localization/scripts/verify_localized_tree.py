#!/usr/bin/env python3
"""Verify a localized Skill-library mirror against its source tree.

Executable content is never run. The verifier compares paths, non-Markdown
bytes, Skill names, frontmatter outside description, fenced blocks, inline
code, URLs, and Markdown link targets.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from collections import Counter
from pathlib import Path

FENCE_RE = re.compile(r'(^```[^\n]*\n.*?^```[ \t]*$|^~~~[^\n]*\n.*?^~~~[ \t]*$)', re.M | re.S)
INLINE_RE = re.compile(r'(`+)(?!`)(.+?)(?<!`)\1(?!`)', re.S)
URL_RE = re.compile(r'https?://[^\s<>\])}]+')
LINK_RE = re.compile(r'!?\[[^\]]*\]\(([^)]+)\)')
NAME_RE = re.compile(r'^name:\s*["\']?([^"\'\n]+)', re.M)
CJK_RE = re.compile(r'[\u3400-\u9fff]')
IGNORED_METADATA_NAMES = {'.DS_Store', 'Thumbs.db', 'desktop.ini'}
IGNORED_METADATA_DIRS = {'__MACOSX'}


def include_file(path: Path, root: Path) -> bool:
    relative = path.relative_to(root)
    return path.name not in IGNORED_METADATA_NAMES and not (set(relative.parts) & IGNORED_METADATA_DIRS)


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def prose_without_code(text: str) -> str:
    return INLINE_RE.sub('', FENCE_RE.sub('', text))


def frontmatter_without_description(text: str) -> str | None:
    if not text.startswith('---\n'):
        return None
    end = text.find('\n---\n', 4)
    if end < 0:
        return None
    lines = text[4:end].splitlines()
    out: list[str] = []
    skipping_description_block = False
    for line in lines:
        if skipping_description_block:
            if line and not line[0].isspace() and re.match(r'^[A-Za-z0-9_-]+:', line):
                skipping_description_block = False
            else:
                continue
        if re.match(r'^description\s*:', line):
            out.append('description: <localized>')
            value = line.split(':', 1)[1].strip()
            if value in {'|', '>-', '>', '|-'}:
                skipping_description_block = True
            continue
        out.append(line)
    return '\n'.join(out)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument('source', type=Path)
    parser.add_argument('destination', type=Path)
    parser.add_argument('--allow-fence-exception', action='append', default=[], metavar='REL_PATH')
    parser.add_argument('--allow-inline-order-exception', action='append', default=[], metavar='REL_PATH')
    parser.add_argument('--allow-inline-exception', action='append', default=[], metavar='REL_PATH',
                        help='Record a manually reviewed inline-parser exception as a warning')
    parser.add_argument('--json', action='store_true')
    args = parser.parse_args()

    source = args.source.resolve()
    destination = args.destination.resolve()
    if not source.is_dir() or not destination.is_dir():
        parser.error('SOURCE and DESTINATION must both be existing directories')
    sf = {str(p.relative_to(source)): p for p in source.rglob('*') if p.is_file() and include_file(p, source)}
    df = {str(p.relative_to(destination)): p for p in destination.rglob('*') if p.is_file() and include_file(p, destination)}
    hard: list[dict[str, object]] = []
    warnings: list[dict[str, object]] = []
    translated_md = 0
    cjk_skill_files = 0

    for rel in sorted(set(sf) - set(df)):
        hard.append({'type': 'missing_file', 'file': rel})
    for rel in sorted(set(df) - set(sf)):
        hard.append({'type': 'extra_file', 'file': rel})

    for rel in sorted(set(sf) & set(df)):
        sp, dp = sf[rel], df[rel]
        if sp.suffix.lower() != '.md':
            if digest(sp) != digest(dp):
                hard.append({'type': 'non_markdown_changed', 'file': rel})
            continue
        try:
            s = sp.read_text(encoding='utf-8')
            d = dp.read_text(encoding='utf-8')
        except UnicodeDecodeError:
            hard.append({'type': 'invalid_utf8', 'file': rel})
            continue

        translated_md += int(s != d)
        if sp.name == 'SKILL.md':
            sn, dn = NAME_RE.search(s), NAME_RE.search(d)
            if (sn.group(1).strip() if sn else None) != (dn.group(1).strip() if dn else None):
                hard.append({'type': 'skill_name_changed', 'file': rel})
            if CJK_RE.search(prose_without_code(d)):
                cjk_skill_files += 1

        sfm = frontmatter_without_description(s)
        dfm = frontmatter_without_description(d)
        if sfm is not None and sfm != dfm:
            hard.append({'type': 'frontmatter_changed_outside_description', 'file': rel})

        source_fences = FENCE_RE.findall(s)
        destination_fences = FENCE_RE.findall(d)
        if source_fences != destination_fences:
            item = {'type': 'fenced_region_changed', 'file': rel,
                    'source_blocks': len(source_fences), 'destination_blocks': len(destination_fences)}
            (warnings if rel in args.allow_fence_exception else hard).append(item)

        so, do = FENCE_RE.sub('', s), FENCE_RE.sub('', d)
        source_inline = [m.group(0) for m in INLINE_RE.finditer(so)]
        destination_inline = [m.group(0) for m in INLINE_RE.finditer(do)]
        if Counter(source_inline) != Counter(destination_inline):
            item = {'type': 'inline_code_changed', 'file': rel}
            (warnings if rel in args.allow_inline_exception else hard).append(item)
        elif source_inline != destination_inline:
            item = {'type': 'inline_code_reordered', 'file': rel}
            allowed = rel in args.allow_inline_order_exception or rel in args.allow_inline_exception
            (warnings if allowed else hard).append(item)

        if Counter(URL_RE.findall(prose_without_code(s))) != Counter(URL_RE.findall(prose_without_code(d))):
            hard.append({'type': 'prose_url_changed', 'file': rel})
        if Counter(LINK_RE.findall(s)) != Counter(LINK_RE.findall(d)):
            hard.append({'type': 'markdown_target_changed', 'file': rel})

    report = {
        'source_files': len(sf),
        'destination_files': len(df),
        'source_skills': sum(1 for p in source.rglob('SKILL.md')),
        'destination_skills': sum(1 for p in destination.rglob('SKILL.md')),
        'translated_markdown_files': translated_md,
        'skill_files_with_cjk_prose': cjk_skill_files,
        'hard_errors': hard,
        'warnings': warnings,
        'ok': not hard,
    }
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(f"skills: {report['source_skills']} -> {report['destination_skills']}")
        print(f"files: {report['source_files']} -> {report['destination_files']}")
        print(f"translated Markdown: {translated_md}")
        print(f"Skill files with CJK prose: {cjk_skill_files}")
        print(f"hard errors: {len(hard)}; warnings: {len(warnings)}")
        for item in hard:
            print('ERROR', json.dumps(item, ensure_ascii=False))
        for item in warnings:
            print('WARN ', json.dumps(item, ensure_ascii=False))
    return 0 if not hard else 1


if __name__ == '__main__':
    sys.exit(main())
