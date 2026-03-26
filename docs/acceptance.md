# Acceptance — showboat-compliance-benchmark

## Delivered Artifacts

- Benchmark dataset for showboat compliance instruction-following
- CLI runner for batch prompting through an external model CLI
- Scoring script for heuristic policy-compliance evaluation
- Project-level documentation and usage instructions

## Acceptance Notes

This delivery is a documentation/tooling project intended for local use. It does not add runtime services or production infrastructure.

## Manual Acceptance Checklist

- [x] Dataset file exists and is valid JSON
- [x] Runner script accepts a CLI template with `{prompt}` placeholder
- [x] Scoring script reads outputs JSON and emits a structured report
- [x] Project README includes usage examples
- [x] Files can be copied or pulled and run locally with Python 3
