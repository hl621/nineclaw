#!/usr/bin/env python3
"""Audit UTF-8, control bytes, relative files, and Markdown anchors."""
from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.parse
from pathlib import Path

FENCE_START_RE = re.compile(r'^\s*(`{3,}|~{3,})')
INLINE_RE = re.compile(r'(`+)(?!`)(.+?)(?<!`)\1(?!`)', re.S)
LINK_RE = re.compile(r'!?\[[^\]]*\]\(([^)]+)\)')
EXPLICIT_ANCHOR_RE = re.compile(
    r'<(?:a|span)\b[^>]*(?:id|name)=["\']([^"\']+)["\'][^>]*>', re.I
)
HEADING_RE = re.compile(r'^#{1,6}\s+(.+?)\s*#*\s*$', re.M)


def visible_markdown(text: str) -> str:
    out: list[str] = []
    inside = False
    marker = ''
    width = 0
    for line in text.splitlines():
        match = FENCE_START_RE.match(line)
        if match:
            token = match.group(1)
            if not inside:
                inside = True
                marker = token[0]
                width = len(token)
            elif token[0] == marker and len(token) >= width:
                inside = False
            continue
        if not inside:
            out.append(line)
    return INLINE_RE.sub('', '\n'.join(out))


def github_slug(heading: str) -> str:
    heading = re.sub(r'<[^>]+>', '', heading)
    heading = re.sub(r'[`*_~]', '', heading).strip().lower()
    heading = ''.join(ch for ch in heading if ch.isalnum() or ch in ' -_')
    return re.sub(r'\s+', '-', heading)


def anchors(path: Path) -> set[str]:
    text = visible_markdown(path.read_text(encoding='utf-8'))
    result = set(EXPLICIT_ANCHOR_RE.findall(text))
    seen: dict[str, int] = {}
    for heading in HEADING_RE.findall(text):
        base = github_slug(heading)
        index = seen.get(base, 0)
        result.add(base if index == 0 else f'{base}-{index}')
        seen[base] = index + 1
    return result


def parse_target(raw: str) -> str:
    value = raw.strip()
    if value.startswith('<') and '>' in value:
        return value[1:value.index('>')]
    if value.startswith('#'):
        return value
    match = re.match(r'^(\S+)(?:\s+["\'(].*)?$', value)
    return match.group(1) if match else value


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument('destination', type=Path)
    parser.add_argument('--json', action='store_true')
    args = parser.parse_args()
    root = args.destination.resolve()
    if not root.is_dir():
        parser.error('DESTINATION must be an existing directory')

    invalid_utf8: list[str] = []
    control_character_files: list[dict[str, object]] = []
    broken_links: list[dict[str, str]] = []
    markdown: dict[Path, str] = {}

    for path in sorted(root.rglob('*.md')):
        rel = str(path.relative_to(root))
        try:
            text = path.read_bytes().decode('utf-8')
        except UnicodeDecodeError:
            invalid_utf8.append(rel)
            continue
        controls = sorted({ord(ch) for ch in text if ord(ch) < 32 and ch not in '\n\r\t'})
        if controls:
            control_character_files.append({'file': rel, 'codepoints': controls})
        markdown[path.resolve()] = visible_markdown(text)

    anchor_cache: dict[Path, set[str]] = {}
    for path, text in markdown.items():
        rel = str(path.relative_to(root))
        for raw in LINK_RE.findall(text):
            target = parse_target(raw)
            if re.match(r'^(?:https?:|mailto:|data:|tel:)', target, re.I):
                continue
            file_part, separator, fragment = target.partition('#')
            if file_part:
                candidate = (path.parent / urllib.parse.unquote(file_part)).resolve()
            else:
                candidate = path
            if not candidate.exists():
                broken_links.append({'file': rel, 'target': target, 'reason': 'missing_file'})
                continue
            if separator and fragment and candidate.suffix.lower() == '.md':
                decoded = urllib.parse.unquote(fragment)
                available = anchor_cache.setdefault(candidate, anchors(candidate))
                if decoded not in available and decoded.lower() not in {item.lower() for item in available}:
                    broken_links.append({'file': rel, 'target': target, 'reason': 'missing_anchor'})

    report = {
        'markdown_files': len(markdown),
        'invalid_utf8': invalid_utf8,
        'control_character_files': control_character_files,
        'broken_internal_links': broken_links,
        'ok': not invalid_utf8 and not control_character_files and not broken_links,
    }
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(f"Markdown files: {report['markdown_files']}")
        print(f"invalid UTF-8: {len(invalid_utf8)}")
        print(f"control-character files: {len(control_character_files)}")
        print(f"broken internal links: {len(broken_links)}")
        for item in invalid_utf8:
            print('ERROR', json.dumps({'type': 'invalid_utf8', 'file': item}, ensure_ascii=False))
        for item in control_character_files:
            print('ERROR', json.dumps({'type': 'control_characters', **item}, ensure_ascii=False))
        for item in broken_links:
            print('ERROR', json.dumps({'type': 'broken_internal_link', **item}, ensure_ascii=False))
    return 0 if report['ok'] else 1


if __name__ == '__main__':
    sys.exit(main())
