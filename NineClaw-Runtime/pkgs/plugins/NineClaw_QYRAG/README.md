# NineClaw-QYRAG

Hermes Agent plugin that wraps QYRAG retrieval APIs as native Hermes tools for RAG workflows.

The intended workflow is:
<!-- 1. Use `QYRAG_answer` for a user's question about the selected knowledge base. -->
1. Search with the user's question or alternate keywords when evidence inspection is needed.
2. Inspect returned chunks directly.
3. If a hit is relevant but incomplete, such as a sentence ending at the chunk boundary, a phrase such as "如下" that introduces following content, or a field name and its value appearing in separate chunks, call `QYRAG_expand_context` with that hit's `dataset_id`, `doc_id` and `chunk_id` to read its neighboring chunks in document order.
4. If the answer contains an exact field, parameter, date, amount, clause, or may have multiple matches in the same document, call `QYRAG_grep_document` with the retrieved `dataset_id` and `doc_id` to verify the exact wording. `QYRAG_grep_document` is a full-document check; it complements, rather than replaces, neighbor expansion.
5. Only answer after the expanded/verified evidence is complete. If it remains insufficient, retry with focused keywords up to about three times. If no new evidence appears, state that the knowledge base does not contain enough evidence; do not infer missing text.

`QYRAG_retrieve` returns relevance-ranked chunks, not the chunks adjacent to a result. Do not pass `chunk_id` to `QYRAG_retrieve` in an attempt to expand context: use `QYRAG_expand_context` instead.

## Tools

<!-- ### `QYRAG_answer`

The default direct-answer tool. It sends the question and the currently selected knowledge-base IDs
to the configured QYRAG answer endpoint (`/api/v1/chat` by default), and returns the grounded answer
with source references. Explicit `dataset_ids` or `dataset_names` override the configured selection.
If neither is passed, set `QYRAG_SELECTED_DATASETS` to the selected IDs or names. -->

### `QYRAG_retrieve`

Full-featured retrieval from QYRAG knowledge bases with support for:
- Semantic search (vector cosine similarity)
- Keyword-based matching (hybrid search)
- Metadata filtering (`and`/`or` logic, 10+ operators)
- Cross-language keyword retrieval
- Knowledge graph enhanced search (`use_kg`)
- TOC enhanced search (`toc_enhance`)
- Reranking via rerank model
- Term highlighting (`<em>` tags)

Returns YAML-style text for Agent reading. Each hit includes:
- `chunk_id`
- `doc_id`
- `dataset_id`
- `doc_name`
- `content`

Retrieval order is only a search ranking. The Agent should judge from the text whether the
chunks can answer the user's question.

### `QYRAG_expand_context`

Fetches chunks before and after a known relevant chunk in the same document. Use this after
`QYRAG_retrieve` when a hit looks relevant but the answer may be in the previous or next
paragraphs. Its required IDs must come from the same retrieved hit:

- `dataset_id`: the hit's `dataset_id`
- `document_id`: the hit's `doc_id`
- `chunk_id`: the hit's `chunk_id`

### `QYRAG_grep_document`

Searches all parsed chunks in one authorized document for a keyword or regular expression. Use it
after retrieval to confirm precise clauses, parameters, dates, amounts, or repeated terms. It does
not establish neighboring order; pair it with `QYRAG_expand_context` when the evidence is split at a
chunk boundary.

### `QYRAG_save_document`

Saves a document into the Hermes workspace for deeper inspection.

- `mode="parsed_text"` exports all parsed chunks as a UTF-8 `.txt` file, suitable for grep.
- `mode="source"` downloads the original source file from QYRAG.

### `QYRAG_health_check`

Quick connectivity check to verify the QYRAG server is reachable and the API key is valid.

## Configuration

Set environment variables in `~/.hermes/.env`:

```bash
QYRAG_BASE_URL=http://172.18.33.24:8513
QYRAG_API_KEY=your_a...
QYRAG_OUTPUT_DIR=qyrag_downloads
QYRAG_DATASETS='[{"name":"政策库","id":"dataset_id_1"},{"name":"法规库","id":"dataset_id_2"}]'
QYRAG_SELECTED_DATASETS='["dataset_id_1"]'
QYRAG_ANSWER_PATH=/api/v1/chat
QYRAG_MAX_RETRIES_HINT=3
```

`QYRAG_DATASETS` is an allowlist. If set, the plugin only searches/saves/expands datasets in this list.
JSON object (`{"name":"id"}`) and CSV (`name=id`) formats are also accepted.
The plugin sends `Authorization: Bearer ...`, matching the NineClaw Manager RAG client.
It also lets the Agent resolve user-facing knowledge-base names through `dataset_names`.
If `QYRAG_API_KEY` is not set, you can pass `api_key` to each tool call.

## Installation

The plugin is auto-discovered from `~/.hermes/plugins/QYRAG_retrieval/`. No install step needed — just place the files there and `/reset` (or restart Hermes).

## Examples

### Basic search
```
QYRAG_retrieve(question="What is QYRAG?", dataset_ids=["<dataset_id>"])
```

### Search by allowed dataset name
```
QYRAG_retrieve(question="...", dataset_names=["政策库"])
```

### Hybrid search with metadata filter
```
QYRAG_retrieve(
    question="performance optimization",
    dataset_ids=["<dataset_id>"],
    keyword=True,
    vector_similarity_weight=0.7,
    similarity_threshold=0.5,
    metadata_condition={
        "logic": "and",
        "conditions": [
            {"name": "author", "comparison_operator": "=", "value": "Toby"}
        ]
    }
)
```

### Expand a specific hit
```
QYRAG_expand_context(
    dataset_id="<dataset_id>",
    document_id="<document_id>",
    chunk_id="<chunk_id>",
    before=2,
    after=3
)
```

### Verify a split parameter across one document
```
# 1. QYRAG_retrieve returns a hit ending with "故宫" and its next chunk begins
#    with "信息分布密度,平均每 500 字至少 1 处".
QYRAG_expand_context(
    dataset_id="<retrieved_dataset_id>",
    document_id="<retrieved_doc_id>",
    chunk_id="<retrieved_chunk_id>",
    before=1,
    after=2
)

# 2. Verify the exact parameter wording in the same document before answering.
QYRAG_grep_document(
    dataset_id="<retrieved_dataset_id>",
    document_id="<retrieved_doc_id>",
    pattern="信息分布"
)
```

### Save a document as grep-friendly text
```
QYRAG_save_document(
    dataset_id="<dataset_id>",
    document_id="<document_id>",
    mode="parsed_text"
)
```

### Download the original file
```
QYRAG_save_document(
    dataset_id="<dataset_id>",
    document_id="<document_id>",
    mode="source",
    filename="source.pdf"
)
```
