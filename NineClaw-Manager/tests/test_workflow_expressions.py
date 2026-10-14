"""Tests for deterministic Condition and Loop expression evaluation."""

import pytest

from app.services.workflow.expressions import ExpressionError, evaluate, resolve_path


def test_evaluate_condition_ast_against_immutable_context():
    context = {"score": 91, "tags": ["verified", "news"], "nested": {"enabled": True}}

    expression = {
        "and": [
            {"gte": [{"path": "score"}, 90]},
            {"in": ["verified", {"path": "tags"}]},
            {"eq": [{"path": "nested.enabled"}, True]},
        ]
    }

    assert evaluate(expression, context) is True


def test_exists_returns_false_for_absent_path():
    assert evaluate({"exists": {"path": "missing.value"}}, {"present": 1}) is False


def test_unknown_operation_and_missing_path_fail_closed():
    with pytest.raises(ExpressionError):
        evaluate({"python": "import os"}, {})
    with pytest.raises(ExpressionError):
        resolve_path({"a": 1}, "b")
