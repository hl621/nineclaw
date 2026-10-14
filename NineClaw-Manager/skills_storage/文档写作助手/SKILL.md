---
name: outline-writing-assistant
title: Outline Writing Assistant
icon: ✍️
description: Use this skill whenever the user needs to write an article, report, document, or any long-form content from an outline, section headings, a mind map, or a table of contents — even if they don't say "outline" explicitly. It expands headings into complete prose, keeps style consistent across sections, and tracks writing progress.
tags: [writing, outline, content-generation, document-writing]
---

# Outline Writing Assistant

Write structured content from an outline, expanding simple section headings into complete, coherent prose.

## When to Use

- Writing a full article or report from an existing outline
- Expanding simple section headings into detailed content
- Multi-section writing that keeps a consistent style throughout
- Generating document content from a mind map or table of contents

## Workflow

### 1. Read the Outline

An outline can come in any of these formats:

**Markdown (recommended):**
```markdown
# Article Title

## Chapter 1: Introduction
- Research background
- Problem statement
- Research significance

## Chapter 2: Core Content
### 2.1 Theoretical Foundation
- Key concepts
- Related theories

### 2.2 Practical Methods
- Step one
- Step two
```

**Simple hierarchical list:**
```
Article Title
  Introduction
    Background
    Problem
  Main Body
    Theory
    Practice
  Conclusion
```

**Plain-text indentation format:**
```
1. Introduction
   1.1 Research background
   1.2 Research significance
2. Main Content
   2.1 Theoretical analysis
   2.2 Case analysis
```

### 2. Parse the Outline Structure

Use the `scripts/analyze.py` script to parse the outline:

```bash
python scripts/analyze.py <outline-file>
```

The script reports:
- Total number of sections
- Maximum nesting depth
- List of section headings
- Suggested writing order

### 3. Write Section by Section

Expand each section of the outline in sequence:

1. **Understand the context**: Re-read what has been written so far and keep the style consistent
2. **Analyze the section's role**:
   - Its position in the outline (beginning / middle / end)
   - Its logical relationship with neighboring sections
   - The depth it should have (overview vs. detail)
3. **Generate content**:
   - Develop the discussion around the heading
   - Add relevant examples, data, or quotes
   - Keep logical transitions between paragraphs

### 4. Style Consistency Check

Use `scripts/analyze.py --style-check` to check style consistency across the document:

```bash
python scripts/analyze.py --style-check <generated-file>
```

Checks include:
- Person consistency (first / second / third person)
- Tense consistency (present / past)
- Tone (formal / casual)
- Paragraph length distribution

## Writing Principles

### Content Expansion Techniques

| Outline Type | Expansion Strategy |
|--------------|-------------------|
| Concept / Definition | Clear definition + illustrative examples + usage scenarios |
| Problem / Challenge | Describe the phenomenon + analyze causes + explain impact |
| Method / Steps | Step-by-step detail + cautions + examples |
| Comparison | Side-by-side presentation + item-by-item comparison + summarize differences |
| Conclusion / Summary | Review key points + distill core message + outlook and recommendations |

### Style Guide

**Academic / technical writing:**
- Use an objective, neutral third person
- Use accurate terminology, explaining when necessary
- Maintain rigorous logic with well-supported arguments
- Use consistent citation formatting

**Business / report writing:**
- Get to the point, conclusions first
- Support claims with data, use charts where appropriate
- Provide actionable recommendations
- Be concise and avoid redundancy

**Blog / general-audience writing:**
- Use a friendly, natural tone
- Make good use of metaphors and stories
- Keep paragraphs and sentences short
- Speak directly to the reader

### Content Quality Checklist

- [ ] Every section has a clear topic sentence
- [ ] Paragraphs flow logically into one another
- [ ] Terminology is used appropriately
- [ ] Examples/data are relevant to the argument
- [ ] No repetition or redundancy
- [ ] The ending echoes the beginning

## Output Format

Generated content keeps the same Markdown structure as the outline:

```markdown
# Title

## Chapter 1

(Expanded content...)

### 1.1 Subsection

(Expanded content...)

## Chapter 2

...
```

## Example

### Input Outline
```markdown
# Benefits and Challenges of Remote Work

## 1. Introduction
- Definition of remote work
- Development trends

## 2. Benefits Analysis
### 2.1 For Individuals
- Flexible hours
- Work-life balance

### 2.2 For Companies
- Cost savings
- Talent acquisition

## 3. Challenges and Responses
- Communication and collaboration
- Self-management

## 4. Conclusion
- Future outlook
```

### Output Requirements
- Total length: 2000–3000 words
- Style: business report
- Audience: corporate executives

### Generation Strategy
1. Start with the introduction to set the background
2. Support the benefits section with data
3. Provide concrete solutions in the challenges section
4. End with a conclusion that echoes the opening and offers recommendations

## Script Tools

### analyze.py - Outline Analysis and Style Check

```bash
# Parse outline structure
python scripts/analyze.py outline.md

# Check style consistency
python scripts/analyze.py --style-check draft.md

# Track writing progress
python scripts/analyze.py --progress outline.md draft.md
```

### write.py - Section Writing Assistant

```bash
# Interactive writing mode
python scripts/write.py

# Generate a writing prompt for a specific section
python scripts/write.py outline.md --chapter "2.1"
```

## Best Practices

1. **Read the whole outline first**: Understand the overall structure and logic before writing
2. **Keep the conversation going**: Confirm anything unclear about the outline with the user first
3. **Deliver in chunks**: For long documents, generate section by section so it's easy to adjust based on feedback
4. **Leave room for revision**: The first draft doesn't need to be perfect; leave space for iterative polishing
5. **Make good use of reference materials**: If the user provides reference materials or sample texts, read them before writing

## Notes

- This skill focuses on structured writing from an outline
- The writing process works fully offline
- For domains that need real-time data (e.g., news, stock markets), ask the user to supply the data
- Respect originality; do not copy large passages directly from reference materials the user provides