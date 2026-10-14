#!/usr/bin/env python3
"""
Chapter writing helper.
Provides interactive writing support and per-section prompt generation.
Uses only the Python standard library.
"""

import sys
import json
import re
from pathlib import Path
from typing import List, Dict, Optional


def load_outline(outline_path: Path) -> List[Dict]:
    """
    Load and parse the outline file.
    """
    from analyze import parse_outline
    content = outline_path.read_text(encoding='utf-8')
    return parse_outline(content)


def flatten_outline(sections: List[Dict]) -> List[Dict]:
    """
    Flatten the outline into a list.
    """
    result = []

    def traverse(secs, parent_path=""):
        for i, sec in enumerate(secs, 1):
            current_path = f"{parent_path}.{i}" if parent_path else str(i)
            sec_copy = {**sec, 'path': current_path}
            result.append(sec_copy)
            traverse(sec['children'], current_path)

    traverse(sections)
    return result


def get_section_by_path(sections: List[Dict], path: str) -> Optional[Dict]:
    """
    Get a section by path (e.g. "2.1").
    """
    flat = flatten_outline(sections)
    for sec in flat:
        if sec['path'] == path:
            return sec
    return None


def get_section_context(sections: List[Dict], target_path: str) -> Dict:
    """
    Get context for a section (previous, next, parent).
    """
    flat = flatten_outline(sections)
    target_idx = None

    for i, sec in enumerate(flat):
        if sec['path'] == target_path:
            target_idx = i
            break

    if target_idx is None:
        return {}

    context = {
        'current': flat[target_idx],
        'previous': flat[target_idx - 1] if target_idx > 0 else None,
        'next': flat[target_idx + 1] if target_idx < len(flat) - 1 else None,
    }

    # Find the parent section
    parent_path = '.'.join(target_path.split('.')[:-1])
    if parent_path:
        context['parent'] = get_section_by_path(sections, parent_path)
    else:
        context['parent'] = None

    return context


def suggest_content_strategy(section: Dict, context: Dict) -> str:
    """
    Suggest a content strategy based on the section type.
    """
    title = section['title'].lower()

    # Determine the section type from keywords in the title
    if any(kw in title for kw in ['introduction', 'intro', 'overview', 'background', 'context']):
        return """
Content strategy: introduction / overview section
- Introduce the topic; explain its background and significance
- State the problem or research goal
- Briefly preview the structure of the article
- Draw the reader in and keep them reading
Suggested length: 200-400 words
"""

    elif any(kw in title for kw in ['conclusion', 'summary', 'outlook', 'recommendation', 'closing', 'future']):
        return """
Content strategy: conclusion section
- Recap the core points of the whole article
- Summarize the main findings or results
- Offer future outlook or action recommendations
- Echo the opening to close the loop
Suggested length: 200-400 words
"""

    elif any(kw in title for kw in ['method', 'step', 'process', 'procedure', 'implementation', 'approach', 'how-to', 'guide']):
        return """
Content strategy: method / how-to section
- Explain the rationale or theoretical basis of the method
- Describe the workflow step by step
- Highlight key points and pitfalls
- Support with examples or code where fitting
Suggested length: 400-800 words
"""

    elif any(kw in title for kw in ['analysis', 'discussion', 'comparison', 'evaluation', 'impact', 'benefit', 'challenge']):
        return """
Content strategy: analysis / discussion section
- Present facts or data
- Analyze and interpret in depth
- Compare different viewpoints or approaches
- Reach a convincing conclusion
Suggested length: 400-800 words
"""

    elif any(kw in title for kw in ['case', 'example', 'sample', 'instance', 'study']):
        return """
Content strategy: case-study section
- Introduce the background of the case
- Describe the specific situation
- Analyze the details of the case
- Extract lessons learned
Suggested length: 300-600 words
"""

    else:
        return """
Content strategy: general expository section
- Develop the argument around the topic
- Provide evidence to support the points
- Keep the logic clear
- Connect naturally with the surrounding sections
Suggested length: 300-600 words
"""


def generate_writing_prompt(section: Dict, context: Dict) -> str:
    """
    Generate a writing prompt.
    """
    prompt_parts = []

    # Section info
    prompt_parts.append(f"Writing: {section['title']}")
    prompt_parts.append(f"Level: {section['level']}")
    prompt_parts.append(f"Path: {section.get('path', 'N/A')}")
    prompt_parts.append("")

    # Context info
    if context.get('parent'):
        prompt_parts.append(f"Parent section: {context['parent']['title']}")
    if context.get('previous'):
        prompt_parts.append(f"Previous section: {context['previous']['title']}")
    if context.get('next'):
        prompt_parts.append(f"Next section: {context['next']['title']}")
    prompt_parts.append("")

    # Content strategy suggestion
    prompt_parts.append(suggest_content_strategy(section, context))

    return '\n'.join(prompt_parts)


def interactive_mode(outline_path: Optional[Path] = None):
    """
    Interactive writing mode.
    """
    sections = []
    flat_sections = []

    if outline_path and outline_path.exists():
        sections = load_outline(outline_path)
        flat_sections = flatten_outline(sections)

    print("=" * 60)
    print("Chapter Writing Assistant")
    print("=" * 60)

    if flat_sections:
        print(f"Loaded outline: {outline_path}")
        print(f"Total sections: {len(flat_sections)}")
        print()
        print("Sections:")
        for sec in flat_sections:
            indent = "  " * (sec['level'] - 1)
            print(f"  [{sec['path']}] {indent}{sec['title']}")
    else:
        print("No outline loaded - free writing mode")

    print()
    print("Commands:")
    print("  <section path>  - show the writing prompt for a section (e.g. 2.1)")
    print("  outline         - display the full outline")
    print("  help            - show help")
    print("  quit            - exit")
    print()

    while True:
        try:
            user_input = input("> ").strip()

            if not user_input:
                continue

            if user_input.lower() in ('quit', 'exit', 'q'):
                print("Goodbye!")
                break

            if user_input.lower() == 'help':
                print("Commands:")
                print("  <section path>  - show the writing prompt for a section")
                print("  outline         - display the full outline")
                print("  help            - show help")
                print("  quit            - exit")
                continue

            if user_input.lower() == 'outline':
                if flat_sections:
                    print("\nFull outline:")
                    for sec in flat_sections:
                        indent = "  " * (sec['level'] - 1)
                        marker = "#" * sec['level']
                        print(f"{marker} {indent}{sec['title']}")
                else:
                    print("No outline loaded")
                print()
                continue

            # Try to interpret the input as a section path
            if flat_sections:
                sec = get_section_by_path(sections, user_input)
                if sec:
                    context = get_section_context(sections, user_input)
                    print()
                    print(generate_writing_prompt(sec, context))
                else:
                    print(f"Section not found: {user_input}")
                    print("Available sections:")
                    for s in flat_sections:
                        print(f"  {s['path']} - {s['title']}")
            else:
                print("No outline loaded; cannot query sections")

        except KeyboardInterrupt:
            print("\nGoodbye!")
            break
        except EOFError:
            break


def export_outline_structure(outline_path: Path, output_path: Path):
    """
    Export the outline structure as JSON.
    """
    sections = load_outline(outline_path)
    flat = flatten_outline(sections)

    data = {
        'total_sections': len(flat),
        'max_level': max((s['level'] for s in flat), default=0),
        'sections': [
            {
                'path': s['path'],
                'level': s['level'],
                'title': s['title']
            }
            for s in flat
        ]
    }

    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    print(f"Outline structure exported to: {output_path}")


def main():
    if len(sys.argv) < 2:
        print("Usage:")
        print("  python write.py                     # interactive mode")
        print("  python write.py <outline-file>          # load an outline, then enter interactive mode")
        print("  python write.py <outline> --chapter <path>  # show the prompt for a section")
        print("  python write.py <outline> --export <output.json>  # export outline structure")
        print()
        print("Examples:")
        print("  python write.py outline.md")
        print("  python write.py outline.md --chapter 2.1")
        sys.exit(1)

    outline_path = Path(sys.argv[1])

    if not outline_path.exists():
        print(f"Error: file not found {outline_path}")
        sys.exit(1)

    # Show a specific section
    if len(sys.argv) >= 4 and sys.argv[2] == '--chapter':
        chapter_path = sys.argv[3]
        sections = load_outline(outline_path)
        sec = get_section_by_path(sections, chapter_path)

        if sec:
            context = get_section_context(sections, chapter_path)
            print(generate_writing_prompt(sec, context))
        else:
            print(f"Section not found: {chapter_path}")
            flat = flatten_outline(sections)
            print("Available sections:")
            for s in flat:
                print(f"  {s['path']} - {s['title']}")
        return

    # Export outline structure
    if len(sys.argv) >= 4 and sys.argv[2] == '--export':
        output_path = Path(sys.argv[3])
        export_outline_structure(outline_path, output_path)
        return

    # Interactive mode
    interactive_mode(outline_path)


if __name__ == "__main__":
    main()