#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
cd "$SCRIPT_DIR"

DATASET_PATH="${EFFECTIVENESS_DATASET:-dataset.json}"
REPORTS_DIR="${EFFECTIVENESS_REPORTS_DIR:-reports}"
OUTPUTS_GLOB="${EFFECTIVENESS_OUTPUTS_GLOB:-outputs-*.json}"
SKILL_PATH="${EFFECTIVENESS_SKILL_PATH:-skills/final-effectiveness-summary}"
ARTIFACTS_DIR="${EFFECTIVENESS_ARTIFACTS_DIR:-artifacts/effectiveness-summary}"
OUTPUT_MARKDOWN="${EFFECTIVENESS_OUTPUT_MARKDOWN:-reports/final-effectiveness-summary.md}"
TIMEOUT_VALUE="${EFFECTIVENESS_TIMEOUT:-${TIMEOUT:-300}}"
INVOKE_JUDGE="${EFFECTIVENESS_INVOKE_JUDGE:-0}"
DEFAULT_REVIEW_RUNNER='opencode run --model {model} --format json'
REVIEW_MODEL="${EFFECTIVENESS_REVIEW_MODEL:-relay-kimi/kimi-k2.5}"
REVIEW_RUNNER="${EFFECTIVENESS_REVIEW_RUNNER:-${OPENCODE_RUNNER_TEMPLATE:-$DEFAULT_REVIEW_RUNNER}}"

args=(
  python3 summarize_effectiveness.py
  --dataset "$DATASET_PATH"
  --reports-dir "$REPORTS_DIR"
  --outputs-glob "$OUTPUTS_GLOB"
  --skill-path "$SKILL_PATH"
  --timeout "$TIMEOUT_VALUE"
  --artifacts-dir "$ARTIFACTS_DIR"
  --output-markdown "$OUTPUT_MARKDOWN"
)

if [[ "$INVOKE_JUDGE" == "1" ]]; then
  args+=(--invoke-judge --review-model "$REVIEW_MODEL" --review-runner "$REVIEW_RUNNER")
else
  if [[ -n "$REVIEW_MODEL" ]]; then
    args+=(--review-model "$REVIEW_MODEL")
  fi
  if [[ -n "$REVIEW_RUNNER" ]]; then
    args+=(--review-runner "$REVIEW_RUNNER")
  fi
fi

"${args[@]}"
