#!/usr/bin/env python3
"""
Outline analysis and writing helper script.
Supports outline structure parsing, style checking, and progress tracking.
Uses only the Python standard library.
"""

import re
import sys
import json
from pathlib import Path
from collections import Counter
from typing import List, Dict, Tuple, Optional


def parse_markdown_outline(content: str) -> List[Dict]:
    """
    Parse a Markdown-format outline.

    Returns:
        A list of sections; each section has level, title, children.
    """
    lines = content.strip().split('\n')
    sections = []
    stack = []

    for line in lines:
        line = line.rstrip()
        if not line:
            continue

        # Match heading lines (# ## ###)
        heading_match = re.match(r'^(#{1,6})\s+(.+)$', line)
        if heading_match:
            level = len(heading_match.group(1))
            title = heading_match.group(2).strip()

            section = {
                'level': level,
                'title': title,
                'children': [],
                'line': line
            }

            # Find the parent section
            while stack and stack[-1]['level'] >= level:
                stack.pop()

            if stack:
                stack[-1]['children'].append(section)
            else:
                sections.append(section)

            stack.append(section)

    return sections


def parse_indent_outline(content: str) -> List[Dict]:
    """
    Parse an indentation-based outline (spaces or tabs).
    """
    lines = content.strip().split('\n')
    sections = []
    stack = []

    for line_num, line in enumerate(lines):
        if not line.strip():
            continue

        # Compute the indentation level
        stripped = line.lstrip()
        indent = len(line) - len(stripped)
        level = indent // 2 + 1  # every 2 spaces counts as one level

        # Strip list markers
        title = re.sub(r'^[\s]*[-*+\d.)]+\s*', '', stripped).strip()

        if not title:
            continue

        section = {
            'level': level,
            'title': title,
            'children': [],
            'line': line
        }

        # Find the parent section
        while stack and stack[-1]['level'] >= level:
            stack.pop()

        if stack:
            stack[-1]['children'].append(section)
        else:
            sections.append(section)

        stack.append(section)

    return sections


def parse_outline(content: str) -> List[Dict]:
    """
    Auto-detect and parse the outline format.
    """
    # Detect Markdown heading format
    if re.search(r'^#{1,6}\s+', content, re.MULTILINE):
        return parse_markdown_outline(content)
    else:
        return parse_indent_outline(content)


def count_sections(sections: List[Dict]) -> Tuple[int, int]:
    """
    Count the number of sections and the maximum nesting level.

    Returns:
        (total section count, maximum level)
    """
    total = 0
    max_level = 0

    def traverse(secs):
        nonlocal total, max_level
        for sec in secs:
            total += 1
            max_level = max(max_level, sec['level'])
            traverse(sec['children'])

    traverse(sections)
    return total, max_level


def flatten_sections(sections: List[Dict]) -> List[Dict]:
    """
    Flatten the section tree into a list.
    """
    result = []

    def traverse(secs):
        for sec in secs:
            result.append(sec)
            traverse(sec['children'])

    traverse(sections)
    return result


def analyze_style(content: str) -> Dict:
    """
    Analyze writing style.
    """
    paragraphs = [p.strip() for p in content.split('\n\n') if p.strip()]
    sentences = re.split(r'[.!?。！？]+', content)
    sentences = [s.strip() for s in sentences if s.strip()]

    # Person analysis
    first_person = len(re.findall(r'\b(?:i|we|my|our|mine|ours)\b', content, re.IGNORECASE))
    second_person = len(re.findall(r'\b(?:you|your|yours)\b', content, re.IGNORECASE))
    third_person = len(re.findall(r'\b(?:he|she|it|they|his|her|its|their|him|them|theirs)\b', content, re.IGNORECASE))

    total_person = first_person + second_person + third_person

    # Paragraph length
    para_lengths = [len(p) for p in paragraphs]
    avg_para_length = sum(para_lengths) / len(para_lengths) if para_lengths else 0

    # Sentence length
    sent_lengths = [len(s) for s in sentences]
    avg_sent_length = sum(sent_lengths) / len(sent_lengths) if sent_lengths else 0

    # Tone markers (rough heuristic for formal vs. casual style)
    formal_markers = len(re.findall(
        r'\b(?:therefore|however|thus|hence|consequently|moreover|furthermore|nevertheless|nonetheless|in conclusion|in summary|in addition)\b',
        content, re.IGNORECASE))
    casual_markers = len(re.findall(
        r'\b(?:gonna|wanna|gotta|kinda|sorta|yeah|yep|nope|okay|ok|hmm|um|uh|lol|btw|awesome|cool|stuff)\b',
        content, re.IGNORECASE))

    return {
        'paragraph_count': len(paragraphs),
        'sentence_count': len(sentences),
        'avg_paragraph_length': round(avg_para_length, 1),
        'avg_sentence_length': round(avg_sent_length, 1),
        'person_perspective': {
            'first': first_person,
            'second': second_person,
            'third': third_person,
            'dominant': max([('first', first_person), ('second', second_person), ('third', third_person)], key=lambda x: x[1])[0] if total_person > 0 else 'neutral'
        },
        'tone': {
            'formal_markers': formal_markers,
            'casual_markers': casual_markers,
            'style': 'formal' if formal_markers > casual_markers else 'casual' if casual_markers > formal_markers else 'neutral'
        }
    }


def check_progress(outline_content: str, draft_content: str) -> Dict:
    """
    Check writing progress.
    """
    outline_sections = parse_outline(outline_content)
    flat_outline = flatten_sections(outline_sections)

    completed = 0
    partial = 0
    not_started = 0

    for sec in flat_outline:
        title = sec['title']
        # Check whether the draft contains this section heading
        if title in draft_content:
            # Check whether there is content after the heading (simple heuristic)
            idx = draft_content.find(title)
            after_title = draft_content[idx + len(title):idx + len(title) + 500]
            # If there is a good amount of text after the heading, treat it as complete
            words = len(re.findall(r'\b\w+\b', after_title))
            if words > 50:
                completed += 1
            else:
                partial += 1
        else:
            not_started += 1

    total = len(flat_outline)
    return {
        'total_sections': total,
        'completed': completed,
        'partial': partial,
        'not_started': not_started,
        'progress_percent': round((completed + partial * 0.5) / total * 100, 1) if total > 0 else 0
    }


def suggest_writing_order(sections: List[Dict]) -> List[str]:
    """
    Suggest a writing order.
    """
    flat = flatten_sections(sections)

    # Return in order, but flag the key sections
    order = []
    for sec in flat:
        indicator = ""
        if sec['level'] == 1:
            indicator = " [main section]"
        elif sec['level'] == 2 and not sec['children']:
            indicator = " [leaf node]"

        indent = "  " * (sec['level'] - 1)
        order.append(f"{indent}{sec['title']}{indicator}")

    return order


def print_outline_analysis(sections: List[Dict]):
    """
    Print the outline analysis result.
    """
    total, max_level = count_sections(sections)

    print("=" * 50)
    print("Outline Structure Analysis")
    print("=" * 50)
    print(f"Total sections: {total}")
    print(f"Maximum depth: {max_level}")
    print()

    print("Suggested writing order:")
    print("-" * 30)
    for item in suggest_writing_order(sections):
        print(item)
    print()


def print_style_analysis(style_info: Dict):
    """
    Print the style analysis result.
    """
    print("=" * 50)
    print("Writing Style Analysis")
    print("=" * 50)
    print(f"Paragraphs: {style_info['paragraph_count']}")
    print(f"Sentences: {style_info['sentence_count']}")
    print(f"Average paragraph length: {style_info['avg_paragraph_length']} chars")
    print(f"Average sentence length: {style_info['avg_sentence_length']} chars")
    print()

    print("Person perspective:")
    person = style_info['person_perspective']
    print(f"  First person: {person['first']}")
    print(f"  Second person: {person['second']}")
    print(f"  Third person: {person['third']}")
    print(f"  Dominant perspective: {person['dominant']}")
    print()

    print("Tone:")
    tone = style_info['tone']
    print(f"  Formal markers: {tone['formal_markers']}")
    print(f"  Casual markers: {tone['casual_markers']}")
    print(f"  Overall style: {tone['style']}")
    print()


def print_progress(progress: Dict):
    """
    Print the progress report.
    """
    print("=" * 50)
    print("Writing Progress")
    print("=" * 50)
    print(f"Total sections: {progress['total_sections']}")
    print(f"Completed: {progress['completed']}")
    print(f"Partially completed: {progress['partial']}")
    print(f"Not started: {progress['not_started']}")
    print(f"Completion: {progress['progress_percent']}%")
    print()

    # Visual progress bar
    bar_length = 30
    filled = int(progress['progress_percent'] / 100 * bar_length)
    bar = '█' * filled + '░' * (bar_length - filled)
    print(f"Progress: [{bar}] {progress['progress_percent']}%")


def main():
    if len(sys.argv) < 2:
        print("Usage:")
        print("  python analyze.py <outline-file>        # Parse outline structure")
        print("  python analyze.py --style-check <draft-file>  # Check style")
        print("  python analyze.py --progress <outline> <draft>  # Check progress")
        print()
        print("Examples:")
        print("  python analyze.py outline.md")
        print("  python analyze.py --style-check draft.md")
        sys.exit(1)

    # Style check mode
    if sys.argv[1] == '--style-check':
        if len(sys.argv) < 3:
            print("Error: please provide a draft file path")
            sys.exit(1)

        draft_path = Path(sys.argv[2])
        if not draft_path.exists():
            print(f"Error: file not found {draft_path}")
            sys.exit(1)

        content = draft_path.read_text(encoding='utf-8')
        style_info = analyze_style(content)
        print_style_analysis(style_info)
        return

    # Progress check mode
    if sys.argv[1] == '--progress':
        if len(sys.argv) < 4:
            print("Error: please provide outline and draft file paths")
            sys.exit(1)

        outline_path = Path(sys.argv[2])
        draft_path = Path(sys.argv[3])

        if not outline_path.exists():
            print(f"Error: outline file not found {outline_path}")
            sys.exit(1)
        if not draft_path.exists():
            print(f"Error: draft file not found {draft_path}")
            sys.exit(1)

        outline_content = outline_path.read_text(encoding='utf-8')
        draft_content = draft_path.read_text(encoding='utf-8')

        progress = check_progress(outline_content, draft_content)
        print_progress(progress)
        return

    # Outline parsing mode
    outline_path = Path(sys.argv[1])
    if not outline_path.exists():
        print(f"Error: file not found {outline_path}")
        sys.exit(1)

    content = outline_path.read_text(encoding='utf-8')
    sections = parse_outline(content)

    if not sections:
        print("Warning: could not parse any section structure")
        print("Please make sure the file contains valid headings (# ## ###) or an indented list")
        sys.exit(1)

    print_outline_analysis(sections)


if __name__ == "__main__":
    main()