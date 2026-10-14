#!/bin/bash
set -e

# Pre-flight check hook — surfaces accumulated learning signals at session start.
# Outputs nothing if there are no signals (zero overhead for clean projects).

LEARNINGS_DIR=".learnings"
EVALS_DIR=".evals"
HANDOFF_DIR=".context-surfing"

# Count learning entries
if [ -f "$LEARNINGS_DIR/LEARNINGS.md" ]; then
  learning_count=$(grep -c '^\## \[LRN-' "$LEARNINGS_DIR/LEARNINGS.md" 2>/dev/null) || learning_count=0
else
  learning_count=0
fi

# Count error entries
if [ -f "$LEARNINGS_DIR/ERRORS.md" ]; then
  error_count=$(grep -c '^\## \[ERR-' "$LEARNINGS_DIR/ERRORS.md" 2>/dev/null) || error_count=0
else
  error_count=0
fi

# Count VERIFIED heals on file (filed by self-healing). Only `Status: verified`
# entries count — `pending-verify` / `abandoned` heals are NOT known-good fixes
# and must not be surfaced as such. Surfaced so the agent applies a proven fix
# before reinventing one.
if [ -f "$LEARNINGS_DIR/HEALS.md" ]; then
  heal_count=$(grep -cE '^\*\*Status\*\*:[[:space:]]*verified' "$LEARNINGS_DIR/HEALS.md" 2>/dev/null) || heal_count=0
else
  heal_count=0
fi

# Count promotion-ready patterns: entries whose Recurrence-Count has reached the
# promotion threshold (>= 3). No skill writes a "promotion_ready" status, so
# readiness is computed from the Recurrence-Count field that self-improvement and
# self-healing actually record. Scans both LEARNINGS.md and HEALS.md.
promo_count=0
for f in "$LEARNINGS_DIR/LEARNINGS.md" "$LEARNINGS_DIR/HEALS.md"; do
  if [ -f "$f" ]; then
    n=$(grep -oiE 'Recurrence-Count[^0-9]*[0-9]+' "$f" 2>/dev/null | grep -oE '[0-9]+$' | awk '$1>=3' | wc -l | tr -d ' ')
    promo_count=$((promo_count + ${n:-0}))
  fi
done

# Count failed evals
if [ -f "$EVALS_DIR/EVAL_INDEX.md" ]; then
  eval_fail_count=$(grep -c '| fail |' "$EVALS_DIR/EVAL_INDEX.md" 2>/dev/null) || eval_fail_count=0
else
  eval_fail_count=0
fi

# Count handoff files
if [ -d "$HANDOFF_DIR" ]; then
  handoff_count=$(find "$HANDOFF_DIR" -name "handoff-*.md" -type f 2>/dev/null | wc -l | tr -d ' ')
else
  handoff_count=0
fi

# Calculate total signals
signals=$((learning_count + error_count + heal_count + promo_count + eval_fail_count + handoff_count))

# Only output if there are signals
if [ "$signals" -gt 0 ]; then
  echo "<pre-flight-check>"
  echo "Active learnings: $learning_count | Recent errors: $error_count | Verified heals: $heal_count | Promotion-ready: $promo_count | Failed evals: $eval_fail_count | Handoffs: $handoff_count"

  # Surface high-priority items
  if [ "$promo_count" -gt 0 ]; then
    echo ""
    echo "Promotion-ready patterns exist — consider running /learning-aggregator."
  fi

  if [ "$eval_fail_count" -gt 0 ]; then
    echo "Failed evals detected — consider running /eval-creator run before starting new work."
  fi

  if [ "$handoff_count" -gt 0 ]; then
    echo "Unread handoff files from previous sessions — read before starting new work."
  fi

  if [ "$heal_count" -gt 0 ]; then
    echo "Verified heals on file in HEALS.md — check for a known fix before reinventing one."
  fi

  echo "</pre-flight-check>"
fi
