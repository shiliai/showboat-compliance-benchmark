# Showboat Compliance Benchmark

A small benchmark for testing whether models obey a strict Showboat execution policy:
**all CLI commands in benchmark answers must use `showboat exec <file> <lang> [code]`**.

## Files

- `dataset.json` — benchmark cases
- `config/hosts.json` — default host context
- `config/models.json` — local model list
- `run_benchmark.py` — invoke a CLI model runner against each prepared case workspace
- `run_all.sh` — batch-run the configured models through the correct CLI
- `score.py` — heuristic scorer for showboat compliance
- `score_strict.py` — stricter scorer for bypass/opacity-sensitive evaluation
- `compare_reports.py` — compare generated reports across models
- `prepare_case_workspace.py` — build per-case workspaces with `AGENTS.md` and `task.txt`
- `execute_outputs.py` — execute model-emitted Showboat workflows and verify markdown artifacts
- `build_benchmark_review.py` — generate benchmark review Showboat documents

## Rule injection via AGENTS.md

This benchmark now evaluates whether models obey rules placed in a per-case `AGENTS.md` file inside the working directory, instead of relying only on inline prompt reminders.

For each `(model, case)` pair, the runner creates a dedicated workspace containing:

- `AGENTS.md` — the benchmark rules and case-specific policy constraints
- `task.txt` — only the task itself (no repeated Showboat rules)
- `case-meta.json` — metadata including the exact markdown log filename and case constraints

The rules require one single legal workflow:

1. `showboat init <file> "Benchmark <file>"`
2. `showboat exec <file> bash "..."`

## Default host context

`config/hosts.json`

```json
{
  "default_host": "localhost"
}
```

The benchmark now assumes a single default target host context, which is `localhost` unless overridden. This keeps the benchmark focused on Showboat workflow compliance rather than multi-host routing semantics.

## Model config

`config/models.json`

```json
{
  "models": [
    "relay-kimi/kimi-k2.5",
    "relay-gpt-sub/gpt-5.4-mini",
    "relay-claude/claude-sonnet-4-6"
  ]
}
```

## CLI routing

`run_all.sh` routes models like this:

- `relay-claude/*` → `bash -lc 'claude_claude -p "{prompt}"'`
- everything else → `opencode run --model ...`

For OpenCode models, the runner auto-detects the binary in this order:

1. `$OPENCODE_BIN`
2. `command -v opencode`
3. `$HOME/.opencode/bin/opencode`

Default template:

```bash
$OPENCODE_BIN run --model {model} --format json "{prompt}"
```

Using `--format json` makes output capture more stable than formatted terminal output.

Recommended Claude wrapper:

```bash
alias claude_claude='cp ~/.claude/claude_settings.json ~/.claude/settings.json && claude --dangerously-skip-permissions'
```

## Designed so an agent can run it directly

If an agent can read this README and has shell access, it should be able to run the benchmark without extra instructions.

### Preconditions

- `showboat` is installed
- `opencode` is installed and available for non-Claude models
- `claude` is installed and available for `relay-claude/*` models
- provider/model credentials are available
- Python **3.9+** is available

## How it works

`run_all.sh` executes the benchmark in four stages:

1. **Prepare per-case workspaces**
   - create `case-workspaces/<model>/<case>/`
   - write `AGENTS.md`, `task.txt`, and `case-meta.json`
2. **Run the model inside that workspace**
   - OpenCode models via `opencode run --format json`
   - Claude relay models via `claude_claude -p`
3. **Score the model output**
   - generate heuristic and strict reports
4. **Optionally execute and audit** (`EXECUTE_OUTPUTS=1`)
   - execute model-emitted Showboat commands
   - generate model artifacts and benchmark review docs

## One-command batch run

```bash
cd benchmark
./run_all.sh
```

## Dry-run preview

```bash
cd benchmark
DRY_RUN=1 ./run_all.sh
```

This previews:

- which models will run
- which CLI runner each model will use
- output/report file targets
- a sample generated `showboat-...md` filename
- a fully copy-pasteable single-model preview command

No model calls are made in dry-run mode, and runner availability checks are skipped as well.

If your keys normally live in `~/.zshrc` or another interactive-shell-only setup, prefer `ENV_FILE=.env.benchmark ./run_all.sh` so the benchmark loads them explicitly.

## Execution validation mode

```bash
EXECUTE_OUTPUTS=1 ./run_all.sh
```

This additionally creates:

- `reports/execute-*.json`
- `artifacts/<model-slug>/showboat-...md` model-generated Showboat documents
- `artifacts/<model-slug>/benchmark-...md` benchmark review documents that capture AGENTS/task/model output/execution summary

## Common variants

Run only a subset:

```bash
ONLY_MODELS='relay-kimi/kimi-k2.5,relay-claude/claude-sonnet-4-6' ./run_all.sh
```

Use alternate config files:

```bash
MODELS_FILE=config/models.example.json HOST_CONFIG=config/hosts.example.json ./run_all.sh
```

Load provider keys from an explicit env file:

```bash
cp .env.example .env.benchmark
# edit .env.benchmark
ENV_FILE=.env.benchmark ./run_all.sh
```

Add CLI flags to the runners:

```bash
OPENCODE_RUNNER_TEMPLATE='$OPENCODE_BIN run --model {model} --format json "{prompt}"' \
CLAUDE_RUNNER_TEMPLATE='bash -lc '\''claude_claude -p "{prompt}"'\''' \
./run_all.sh
```

## Compare reports

```bash
python3 compare_reports.py
python3 compare_reports.py --case-matrix
python3 compare_reports.py --format csv --case-matrix > comparison.csv
```
