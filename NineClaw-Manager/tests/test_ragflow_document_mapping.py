from app.services.ragflow_knowledge_service import _map_document


def test_map_document_preserves_ragflow_progress_and_failure_reason() -> None:
    mapped = _map_document(
        {
            "id": "doc-1",
            "name": "broken.pdf",
            "run": "FAIL",
            "progress": 0.42,
            "progress_msg": "Parser error: invalid PDF structure",
        }
    )

    assert mapped["parse_failed"] is True
    assert mapped["progress"] == 0.42
    assert mapped["progress_msg"] == "Parser error: invalid PDF structure"


def test_map_document_normalizes_optional_progress_fields() -> None:
    mapped = _map_document(
        {
            "id": "doc-2",
            "name": "pending.txt",
            "run": "RUNNING",
            "progress": "0.5",
            "progress_msg": "  ",
        }
    )

    assert mapped["progress"] == 0.5
    assert mapped["progress_msg"] is None
