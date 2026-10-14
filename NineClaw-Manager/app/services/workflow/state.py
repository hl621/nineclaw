"""Workflow state constants and transition predicates."""

from __future__ import annotations


RUN_TERMINAL = {"succeeded", "failed", "cancelled"}
NODE_TERMINAL = {"succeeded", "failed", "skipped", "blocked", "cancelled"}
NODE_ACTIVE = {
    "pending",
    "ready",
    "dispatching",
    "running",
    "stop_requested",
    "uncertain",
    "stop_unconfirmed",
}
ATTENTION_NODE_STATES = {"uncertain", "stop_unconfirmed"}

EDGE_PENDING = "pending"
EDGE_TAKEN = "taken"
EDGE_NOT_SELECTED = "not_selected"
EDGE_BLOCKED = "blocked"


def is_node_terminal(status: str) -> bool:
    return status in NODE_TERMINAL


def is_run_terminal(status: str) -> bool:
    return status in RUN_TERMINAL
