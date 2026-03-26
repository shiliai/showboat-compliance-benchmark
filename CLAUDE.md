# Project Instructions — showboat-compliance-benchmark

## Current Phase

- Active phase: **Phase 4 — Documentation-only delivery**
- Scope: benchmark dataset, runner scripts, scoring scripts, and usage docs

## Rules

1. Keep scope tightly limited to benchmark artifacts for testing execution-path compliance.
2. Do not introduce infrastructure dependencies beyond Python 3 and the external CLI runner provided by the user (for example `opencode`).
3. Prefer CLI-agnostic interfaces with a runner template rather than hardcoding one provider.
4. Optimize for reproducibility, inspectability, and ease of local use.
5. Treat this project as a local evaluation harness, not a production service.
