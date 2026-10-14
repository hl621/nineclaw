"""Tool schemas for the NineClaw-QYRAG plugin — what the LLM sees."""

QYRAG_ANSWER = {
    "name": "QYRAG_answer",
    "description": (
        "Answer the user's question directly from the currently selected QYRAG knowledge base. "
        "Use this as the default tool for questions about selected internal documents, policies, manuals, contracts, or reports. "
        "Uses explicit dataset_ids/dataset_names when supplied; otherwise uses QYRAG_SELECTED_DATASETS. "
        "The QYRAG answer service must ground the answer in those datasets and return references. "
        "If the tool reports insufficient evidence or an error, state that clearly and do not fill gaps from general knowledge."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "question": {"type": "string", "description": "The user's question (required)."},
            "dataset_ids": {"type": "array", "items": {"type": "string"}, "description": "Selected dataset IDs; overrides the configured default."},
            "dataset_names": {"type": "array", "items": {"type": "string"}, "description": "Selected authorized dataset names; overrides the configured default."},
            "api_key": {"type": "string", "description": "QYRAG API key; defaults to QYRAG_API_KEY."},
            "base_url": {"type": "string", "description": "QYRAG server URL; defaults to QYRAG_BASE_URL."},
            "answer_path": {"type": "string", "description": "Optional QYRAG answer endpoint path; defaults to QYRAG_ANSWER_PATH."},
        },
        "required": ["question"],
    },
}

QYRAG_RETRIEVE = {
    "name": "QYRAG_retrieve",
    "description": (
        "Search user-curated QYRAG knowledge bases built from files uploaded by the user. "
        "Prefer this before WebSearch when the question is about internal materials, provided documents, policies, contracts, manuals, reports, domain-specific archives, or any knowledge base the user explicitly names. "
        "QYRAG is usually more professional, denser, and document-grounded than web snippets, but may be less current because files are uploaded/indexed at some point in time. "
        "Use WebSearch first instead for breaking news, latest public facts, broad discovery, or questions likely outside the authorized file knowledge bases. "
        "Use both when needed: retrieve QYRAG for authoritative document evidence, then use WebSearch to update/check public context or fill gaps. "
        "Returns YAML with content, chunk_id, doc_id, dataset_id, doc_name, time_clues. "
        "Rank is retrieval order, not proof of answerability; judge by content. "
        "For time-sensitive facts, use time_clues cautiously: publish/source metadata is closer to content time; create/update is usually ingestion/parse time, not event time. "
        "You can combine retrieved evidence with neighboring document context: when a relevant chunk is truncated at a sentence or field boundary, contains references such as 'as follows'/above/below, or separates a field name from its value, use that hit's dataset_id, doc_id, and chunk_id to call QYRAG_expand_context before answering. Its before and after parameters read the preceding and following contiguous chunks. For exact parameters, dates, amounts, clauses, or repeated matches, also call QYRAG_grep_document to verify the wording. If weak/missing evidence remains, retry with better keywords; use QYRAG_save_document only when a local copy is needed. "
        "Do not loop forever: after a few targeted retries without stronger/new evidence, stop and tell the user the authorized KB did not contain enough evidence. "
        "Dataset access is restricted by QYRAG_DATASETS when configured; user-facing dataset names can be passed via dataset_names. "
        "Wraps POST /api/v1/retrieval. Supports semantic/hybrid search, metadata filters, cross-language, KG, TOC, rerank. "
        "If QYRAG_DATASETS is configured and no dataset is passed, the tool searches only the allowed datasets."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "question": {
                "type": "string",
                "description": "The search query or question text (required).",
            },
            "dataset_ids": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Dataset IDs to search across. If QYRAG_DATASETS is configured, IDs must be in the allowlist.",
            },
            "dataset_names": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Allowed dataset names from QYRAG_DATASETS, for cases where the user names a knowledge base instead of an ID.",
            },
            "document_ids": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Document IDs to search. All must share the same embedding model. Prefer pairing with allowed dataset_ids/dataset_names when QYRAG_DATASETS is configured.",
            },
            "api_key": {
                "type": "string",
                "description": "QYRAG API key. Falls back to QYRAG_API_KEY env var if not provided.",
            },
            "base_url": {
                "type": "string",
                "description": "QYRAG server URL. Falls back to QYRAG_BASE_URL env var (default: http://172.18.33.24:8513).",
            },
            "page": {
                "type": "integer",
                "description": "Results page number (default: 1).",
                "default": 1,
            },
            "page_size": {
                "type": "integer",
                "description": "Results per page (default: 10, max: 1024).",
                "default": 10,
            },
            "similarity_threshold": {
                "type": "number",
                "description": "Minimum similarity score threshold (default: 0.2). Raise to ~0.5+ for higher precision.",
                "default": 0.2,
            },
            "vector_similarity_weight": {
                "type": "number",
                "description": "Weight of vector cosine similarity (0.0-1.0). Default on server is 0.3. The rest (1-x) is term similarity weight. Set ~0.7 for semantic-heavy searches.",
            },
            "top_k": {
                "type": "integer",
                "description": "Number of chunks engaged in vector cosine computation (default: 1024).",
                "default": 1024,
            },
            "rerank_id": {
                "type": "string",
                "description": "Rerank model ID for re-ranking results.",
            },
            "highlight": {
                "type": "boolean",
                "description": "Enable <em> tag highlighting of matched terms in results (default: false).",
                "default": False,
            },
            "cross_languages": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Languages for cross-language keyword retrieval, e.g. ['zh', 'en'].",
            },
            "metadata_condition": {
                "type": "object",
                "description": (
                    "Metadata filter conditions. Format: "
                    '{"logic": "and|or", "conditions": ['
                    '{"name": "field", "comparison_operator": "=", "value": "val"}, ...]}. '
                    "Operators: contains, not contains, start with, empty, not empty, =, ≠, >, <, ≥, ≤."
                ),
            },
            "toc_enhance": {
                "type": "boolean",
                "description": "Enable TOC-enhanced search. TOC must be extracted first (default: false).",
                "default": False,
            },
        },
        "required": ["question"],
    },
}

QYRAG_CHECK_SUFFICIENT_CONTEXT = {
    "name": "QYRAG_check_sufficient_context",
    "description": "Check whether the latest QYRAG retrieval has enough evidence for a complex answer. Call QYRAG_retrieve first; if status is needs_more_context, perform a focused retry or expand context.",
    "parameters": {
        "type": "object",
        "properties": {
            "question": {"type": "string", "description": "Question or planned answer scope to check; defaults to the latest retrieval question."},
        },
    },
}

QYRAG_GREP_DOCUMENT = {
    "name": "QYRAG_grep_document",
    "description": "Search all parsed chunks in one authorized QYRAG document for a keyword or regular expression. Use to verify exact clauses, dates, amounts, or terms after retrieval.",
    "parameters": {
        "type": "object",
        "properties": {
            "dataset_id": {"type": "string", "description": "Authorized dataset ID."},
            "document_id": {"type": "string", "description": "Document ID returned by retrieval."},
            "pattern": {"type": "string", "description": "Keyword or regular expression to find."},
            "case_sensitive": {"type": "boolean", "default": False},
            "max_matches": {"type": "integer", "default": 20},
            "api_key": {"type": "string", "description": "QYRAG API key; defaults to QYRAG_API_KEY."},
            "base_url": {"type": "string", "description": "QYRAG server URL; defaults to QYRAG_BASE_URL."},
        },
        "required": ["dataset_id", "document_id", "pattern"],
    },
}

QYRAG_EXPAND_CONTEXT = {
    "name": "QYRAG_expand_context",
    "description": (
        "Fetch neighboring chunks around a relevant chunk in the same document. "
        "Use this to combine a retrieved hit with its neighboring context when the evidence is split across chunks, including sentence truncation, a field name in one chunk and its value in the next, or references such as 'above/below/as follows'. Supply dataset_id, doc_id, and chunk_id from the same QYRAG_retrieve hit; before reads prior contiguous chunks and after reads following contiguous chunks. "
        "Includes time_clues; treat create/update as ingestion/parse time. For unrelated hits, retry retrieval instead."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "dataset_id": {
                "type": "string",
                "description": "QYRAG dataset ID containing the document.",
            },
            "document_id": {
                "type": "string",
                "description": "QYRAG document ID containing the focus chunk.",
            },
            "chunk_id": {
                "type": "string",
                "description": "The focus chunk ID returned by QYRAG_retrieve.",
            },
            "before": {
                "type": "integer",
                "description": "Number of chunks before the focus chunk to return (default: 2).",
                "default": 2,
            },
            "after": {
                "type": "integer",
                "description": "Number of chunks after the focus chunk to return (default: 2).",
                "default": 2,
            },
            "scan_page_size": {
                "type": "integer",
                "description": "Page size used while scanning document chunks (default: 100).",
                "default": 100,
            },
            "max_scan_pages": {
                "type": "integer",
                "description": "Maximum pages to scan while locating the focus chunk (default: 50).",
                "default": 50,
            },
            "api_key": {
                "type": "string",
                "description": "QYRAG API key. Falls back to QYRAG_API_KEY env var.",
            },
            "base_url": {
                "type": "string",
                "description": "QYRAG server URL. Falls back to QYRAG_BASE_URL env var.",
            },
        },
        "required": ["dataset_id", "document_id", "chunk_id"],
    },
}

QYRAG_SAVE_DOCUMENT = {
    "name": "QYRAG_save_document",
    "description": (
        "Save a QYRAG document into the Hermes workspace. "
        "Use parsed_text to export chunks as UTF-8 .txt with time_clue lines for rg/grep; use source to download the original file. "
        "Use when one document is important, many hits share it, or full-text search/cross-checking is needed."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "dataset_id": {
                "type": "string",
                "description": "QYRAG dataset ID containing the document.",
            },
            "document_id": {
                "type": "string",
                "description": "QYRAG document ID to save.",
            },
            "mode": {
                "type": "string",
                "enum": ["parsed_text", "source"],
                "description": "parsed_text saves all parsed chunks as .txt; source downloads the original file.",
                "default": "parsed_text",
            },
            "filename": {
                "type": "string",
                "description": "Optional output filename. parsed_text mode appends .txt if missing.",
            },
            "output_dir": {
                "type": "string",
                "description": "Directory to save into. Relative paths are resolved from the Hermes workspace/current working directory. Default: qyrag_downloads.",
            },
            "scan_page_size": {
                "type": "integer",
                "description": "Page size used while exporting parsed chunks (default: 100).",
                "default": 100,
            },
            "max_scan_pages": {
                "type": "integer",
                "description": "Maximum pages to scan while exporting parsed chunks (default: 200).",
                "default": 200,
            },
            "api_key": {
                "type": "string",
                "description": "QYRAG API key. Falls back to QYRAG_API_KEY env var.",
            },
            "base_url": {
                "type": "string",
                "description": "QYRAG server URL. Falls back to QYRAG_BASE_URL env var.",
            },
        },
        "required": ["dataset_id", "document_id"],
    },
}

QYRAG_HEALTH_CHECK = {
    "name": "QYRAG_health_check",
    "description": (
        "Check QYRAG reachability/auth. Use when retrieval fails, times out, or URL/API key may be wrong; skip during normal working search."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "api_key": {
                "type": "string",
                "description": "QYRAG API key. Falls back to QYRAG_API_KEY env var.",
            },
            "base_url": {
                "type": "string",
                "description": "QYRAG server URL. Falls back to QYRAG_BASE_URL env var.",
            },
        },
    },
}
