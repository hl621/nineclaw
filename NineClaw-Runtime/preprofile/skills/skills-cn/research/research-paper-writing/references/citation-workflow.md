# 引文管理与幻觉防范

本文提供一套完整的工作流程，用于以编程方式管理引文、防止 AI 生成虚假引文，并维护整洁的参考文献库。

---

## 目录

- [为什么引文验证很重要](#why-citation-verification-matters)
- [引文 API 概述](#citation-apis-overview)
- [验证引文工作流程](#verified-citation-workflow)
- [Python 实施](#python-implementation)
- [BibTeX 管理](#bibtex-management)
- [常见引文格式](#common-citation-formats)
- [故障排除](#troubleshooting)

---

<a id="why-citation-verification-matters"></a>

## 为什么引文验证很重要

### 幻觉问题

已有研究表明，AI 生成的引文存在严重问题：
- AI 生成引文的**错误率约为 40%**（Enago Academy 研究）
- NeurIPS 2025 发现，有 **100 多条虚假引文**漏过了评审
- 常见错误包括：
  - 使用真实作者姓名，捏造论文标题
  - 发表会议／期刊或年份错误
  - 论文并不存在，但元数据看似可信
  - DOI 或 arXiv ID 错误

### 后果

- 在某些会议或期刊遭直接拒稿
- 失去审稿人的信任
- 论文发表后可能被撤稿
- 浪费时间查找并不存在的来源

### 解决方案

**绝不要凭记忆生成引文——务必通过程序验证。**

---

<a id="citation-apis-overview"></a>

## 引文 API 概述

### 主要 API

| API | 覆盖范围 | 速率限制 | 最适合 |
|-----|----------|-------------|----------|
| **Semantic Scholar** | 2.14 亿篇论文 | 1 RPS（免费密钥） | ML/AI 论文、引文图谱 |
| **CrossRef** | 1.4 亿多个 DOI | 提供 mailto 的礼貌请求池 | DOI 查询、BibTeX 获取 |
| **arXiv** | 预印本 | 请求间隔 3 秒 | ML 预印本、PDF 获取 |
| **OpenAlex** | 2.4 亿多项成果 | 每天 10 万次、10 RPS | MAG 的开放替代方案 |

### API 选型指南

```
Need ML paper search? → Semantic Scholar
Have DOI, need BibTeX? → CrossRef content negotiation
Looking for preprint? → arXiv API
Need open data, bulk access? → OpenAlex
```

### 无官方 Google Scholar API

Google Scholar 没有官方 API，抓取其页面违反服务条款。只有当 Semantic Scholar 的覆盖范围不足时，才考虑使用 SerpApi（每月 75–275 美元）。

---

<a id="verified-citation-workflow"></a>

## 验证引文工作流程

### 五步流程

```
1. SEARCH → Query Semantic Scholar with specific keywords
     ↓
2. VERIFY → Confirm paper exists in 2+ sources
     ↓
3. RETRIEVE → Get BibTeX via DOI content negotiation
     ↓
4. VALIDATE → Confirm the claim appears in source
     ↓
5. ADD → Add verified entry to .bib file
```

### 第 1 步：搜索

使用 Semantic Scholar 搜索 ML/AI 论文：

```python
from semanticscholar import SemanticScholar

sch = SemanticScholar()
results = sch.search_paper("transformer attention mechanism", limit=10)

for paper in results:
    print(f"Title: {paper.title}")
    print(f"Year: {paper.year}")
    print(f"DOI: {paper.externalIds.get('DOI', 'N/A')}")
    print(f"arXiv: {paper.externalIds.get('ArXiv', 'N/A')}")
    print(f"Citation count: {paper.citationCount}")
    print("---")
```

### 第 2 步：验证论文是否存在

确认至少有两个来源收录了该论文：

```python
import requests

def verify_paper(doi=None, arxiv_id=None, title=None):
    """Verify paper exists in multiple sources."""
    sources_found = []

    # Check Semantic Scholar
    sch = SemanticScholar()
    if doi:
        paper = sch.get_paper(f"DOI:{doi}")
        if paper:
            sources_found.append("Semantic Scholar")

    # Check CrossRef (via DOI)
    if doi:
        resp = requests.get(f"https://api.crossref.org/works/{doi}")
        if resp.status_code == 200:
            sources_found.append("CrossRef")

    # Check arXiv
    if arxiv_id:
        resp = requests.get(
            f"http://export.arxiv.org/api/query?id_list={arxiv_id}"
        )
        if "<entry>" in resp.text:
            sources_found.append("arXiv")

    return len(sources_found) >= 2, sources_found
```

### 第 3 步：获取 BibTeX

使用 DOI 内容协商机制，确保信息准确：

```python
import requests

def doi_to_bibtex(doi: str) -> str:
    """Get verified BibTeX from DOI via CrossRef content negotiation."""
    response = requests.get(
        f"https://doi.org/{doi}",
        headers={"Accept": "application/x-bibtex"},
        allow_redirects=True
    )
    response.raise_for_status()
    return response.text

# Example: "Attention Is All You Need"
bibtex = doi_to_bibtex("10.48550/arXiv.1706.03762")
print(bibtex)
```

### 第 4 步：核实论断

在用论文支撑某项具体论断之前，应核实原文中确实包含该论断：

```python
def get_paper_abstract(doi):
    """Get abstract to verify claims."""
    sch = SemanticScholar()
    paper = sch.get_paper(f"DOI:{doi}")
    return paper.abstract if paper else None

# Verify claim appears in abstract
abstract = get_paper_abstract("10.48550/arXiv.1706.03762")
claim = "attention mechanism"
if claim.lower() in abstract.lower():
    print("Claim appears in paper")
```

### 第 5 步：加入参考文献库

采用统一的引用键格式，将已验证的条目加入 .bib 文件：

```python
def generate_citation_key(bibtex: str) -> str:
    """Generate consistent citation key: author_year_firstword."""
    import re

    # Extract author
    author_match = re.search(r'author\s*=\s*\{([^}]+)\}', bibtex, re.I)
    if author_match:
        first_author = author_match.group(1).split(',')[0].split()[-1]
    else:
        first_author = "unknown"

    # Extract year
    year_match = re.search(r'year\s*=\s*\{?(\d{4})\}?', bibtex, re.I)
    year = year_match.group(1) if year_match else "0000"

    # Extract title first word
    title_match = re.search(r'title\s*=\s*\{([^}]+)\}', bibtex, re.I)
    if title_match:
        first_word = title_match.group(1).split()[0].lower()
        first_word = re.sub(r'[^a-z]', '', first_word)
    else:
        first_word = "paper"

    return f"{first_author.lower()}_{year}_{first_word}"
```

---

<a id="python-implementation"></a>

## Python 实现

### 完整的引文管理器类

{% raw %}
```python
"""
Citation Manager - Verified citation workflow for ML papers.
"""

import requests
import time
from typing import Optional, List, Dict, Tuple
from dataclasses import dataclass

try:
    from semanticscholar import SemanticScholar
except ImportError:
    print("Install: pip install semanticscholar")
    SemanticScholar = None

@dataclass
class Paper:
    title: str
    authors: List[str]
    year: int
    doi: Optional[str]
    arxiv_id: Optional[str]
    venue: Optional[str]
    citation_count: int
    abstract: Optional[str]

class CitationManager:
    """Manage citations with verification."""

    def __init__(self, api_key: Optional[str] = None):
        self.sch = SemanticScholar(api_key=api_key) if SemanticScholar else None
        self.verified_papers: Dict[str, Paper] = {}

    def search(self, query: str, limit: int = 10) -> List[Paper]:
        """Search for papers using Semantic Scholar."""
        if not self.sch:
            raise RuntimeError("Semantic Scholar not available")

        results = self.sch.search_paper(query, limit=limit)
        papers = []

        for r in results:
            paper = Paper(
                title=r.title,
                authors=[a.name for a in (r.authors or [])],
                year=r.year or 0,
                doi=r.externalIds.get('DOI') if r.externalIds else None,
                arxiv_id=r.externalIds.get('ArXiv') if r.externalIds else None,
                venue=r.venue,
                citation_count=r.citationCount or 0,
                abstract=r.abstract
            )
            papers.append(paper)

        return papers

    def verify(self, paper: Paper) -> Tuple[bool, List[str]]:
        """Verify paper exists in multiple sources."""
        sources = []

        # Already found in Semantic Scholar via search
        sources.append("Semantic Scholar")

        # Check CrossRef if DOI available
        if paper.doi:
            try:
                resp = requests.get(
                    f"https://api.crossref.org/works/{paper.doi}",
                    timeout=10
                )
                if resp.status_code == 200:
                    sources.append("CrossRef")
            except Exception:
                pass

        # Check arXiv if ID available
        if paper.arxiv_id:
            try:
                resp = requests.get(
                    f"http://export.arxiv.org/api/query?id_list={paper.arxiv_id}",
                    timeout=10
                )
                if "<entry>" in resp.text and "<title>" in resp.text:
                    sources.append("arXiv")
            except Exception:
                pass

        return len(sources) >= 2, sources

    def get_bibtex(self, paper: Paper) -> Optional[str]:
        """Get BibTeX for verified paper."""
        if paper.doi:
            try:
                resp = requests.get(
                    f"https://doi.org/{paper.doi}",
                    headers={"Accept": "application/x-bibtex"},
                    timeout=10,
                    allow_redirects=True
                )
                if resp.status_code == 200:
                    return resp.text
            except Exception:
                pass

        # Fallback: generate from paper data
        return self._generate_bibtex(paper)

    def _generate_bibtex(self, paper: Paper) -> str:
        """Generate BibTeX from paper metadata."""
        # Generate citation key
        first_author = paper.authors[0].split()[-1] if paper.authors else "unknown"
        first_word = paper.title.split()[0].lower().replace(',', '').replace(':', '')
        key = f"{first_author.lower()}_{paper.year}_{first_word}"

        # Format authors
        authors = " and ".join(paper.authors) if paper.authors else "Unknown"

        bibtex = f"""@article{{{key},
  title = {{{paper.title}}},
  author = {{{authors}}},
  year = {{{paper.year}}},
  {'doi = {' + paper.doi + '},' if paper.doi else ''}
  {'eprint = {' + paper.arxiv_id + '},' if paper.arxiv_id else ''}
  {'journal = {' + paper.venue + '},' if paper.venue else ''}
}}"""
        return bibtex

    def cite(self, query: str) -> Optional[str]:
        """Full workflow: search, verify, return BibTeX."""
        # Search
        papers = self.search(query, limit=5)
        if not papers:
            return None

        # Take top result
        paper = papers[0]

        # Verify
        verified, sources = self.verify(paper)
        if not verified:
            print(f"Warning: Could only verify in {sources}")

        # Get BibTeX
        bibtex = self.get_bibtex(paper)

        # Cache
        if bibtex:
            self.verified_papers[paper.title] = paper

        return bibtex


# Usage example
if __name__ == "__main__":
    cm = CitationManager()

    # Search and cite
    bibtex = cm.cite("attention is all you need transformer")
    if bibtex:
        print(bibtex)
```
{% endraw %}

### 便捷函数

```python
def quick_cite(query: str) -> str:
    """One-liner citation."""
    cm = CitationManager()
    return cm.cite(query)

def batch_cite(queries: List[str], output_file: str = "references.bib"):
    """Cite multiple papers and save to file."""
    cm = CitationManager()
    bibtex_entries = []

    for query in queries:
        print(f"Processing: {query}")
        bibtex = cm.cite(query)
        if bibtex:
            bibtex_entries.append(bibtex)
        time.sleep(1)  # Rate limiting

    with open(output_file, 'w') as f:
        f.write("\n\n".join(bibtex_entries))

    print(f"Saved {len(bibtex_entries)} citations to {output_file}")
```

---

<a id="bibtex-management"></a>

## BibTeX 管理

### BibTeX 与 BibLaTeX 对比

| 功能 | BibTeX | BibLaTeX |
|---------|--------|----------|
| Unicode 支持 | 有限 | 完整 |
| 条目类型 | 标准 | 扩展（@online、@dataset） |
| 自定义能力 | 有限 | 高度灵活 |
| 后端 | bibtex | Biber（推荐） |

**建议**：会议投稿使用 natbib 与 BibTeX——NeurIPS、ICML、ICLR、ACL、AAAI、COLM 等主要会议的模板均附带 natbib 和 `.bst` 文件。对于期刊论文或可自行控制模板的个人项目，可以选择 BibLaTeX 与 Biber。

### LaTeX 设置

```latex
% In preamble
\usepackage[
    backend=biber,
    style=numeric,
    sorting=none
]{biblatex}
\addbibresource{references.bib}

% In document
\cite{vaswani_2017_attention}

% At end
\printbibliography
```

### 引文命令

```latex
\cite{key}      % Numeric: [1]
\citep{key}     % Parenthetical: (Author, 2020)
\citet{key}     % Textual: Author (2020)
\citeauthor{key} % Just author name
\citeyear{key}  % Just year
```

### 统一的引用键

使用格式：`author_year_firstword`

```
vaswani_2017_attention
devlin_2019_bert
brown_2020_language
```

---

<a id="common-citation-formats"></a>

## 常见引文格式

### 会议论文

```bibtex
@inproceedings{vaswani_2017_attention,
  title = {Attention Is All You Need},
  author = {Vaswani, Ashish and Shazeer, Noam and Parmar, Niki and
            Uszkoreit, Jakob and Jones, Llion and Gomez, Aidan N and
            Kaiser, Lukasz and Polosukhin, Illia},
  booktitle = {Advances in Neural Information Processing Systems},
  volume = {30},
  year = {2017},
  publisher = {Curran Associates, Inc.}
}
```

### 期刊论文

```bibtex
@article{hochreiter_1997_long,
  title = {Long Short-Term Memory},
  author = {Hochreiter, Sepp and Schmidhuber, J{\"u}rgen},
  journal = {Neural Computation},
  volume = {9},
  number = {8},
  pages = {1735--1780},
  year = {1997},
  publisher = {MIT Press}
}
```

### arXiv 预印本

```bibtex
@misc{brown_2020_language,
  title = {Language Models are Few-Shot Learners},
  author = {Brown, Tom and Mann, Benjamin and Ryder, Nick and others},
  year = {2020},
  eprint = {2005.14165},
  archiveprefix = {arXiv},
  primaryclass = {cs.CL}
}
```

---

<a id="troubleshooting"></a>

## 故障排除

### 常见问题

**问题：Semantic Scholar 未返回结果**
- 尝试更具体的关键词
- 检查作者姓名的拼写
- 对确切的短语使用引号

**问题：DOI 无法解析为 BibTeX**
- DOI 可能已注册但未链接到 CrossRef
- 如有 arXiv ID，请改用该 ID
- 从元数据手动生成 BibTeX

**问题：速率限制错误**
- 在请求之间添加延迟（1-3 秒）
- 如果可用，请使用 API 密钥
- 缓存结果以避免重复查询

**问题：BibTeX 中出现编码问题**
- 使用正确的 LaTeX 转义：`{\"u}` for ü
- 确保文件是 UTF-8 编码的
- 将 BibLaTeX 与 Biber 结合使用以获得更好的 Unicode

### 验证清单

添加引文之前：

- [ ] 至少在 2 个来源中找到论文
- [ ] DOI 或 arXiv ID 已验证
- [ ] BibTeX 已通过检索获得（而非凭记忆生成）
- [ ] 条目类型正确（@inproceedings 与 @article）
- [ ] 作者姓名完整且格式正确
- [ ] 年份和发表会议／期刊已验证
- [ ] 引用键遵循统一格式

---

## 其他资源

**API：**
- Semantic Scholar：https://api.semanticscholar.org/api-docs/
- CrossRef：https://www.crossref.org/documentation/retrieve-metadata/rest-api/
- arXiv：https://info.arxiv.org/help/api/basics.html
- OpenAlex：https://docs.openalex.org/

**Python 库：**
- `semanticscholar`：https://pypi.org/project/semanticscholar/
- `arxiv`：https://pypi.org/project/arxiv/
- `habanero`（CrossRef）：https://github.com/sckott/habanero

**验证工具：**
- Citely：https://citely.ai/citation-checker
- ReciteWorks：https://reciteworks.com/
