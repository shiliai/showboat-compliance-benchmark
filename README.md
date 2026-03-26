# showboat-compliance-benchmark

A small benchmark project for testing whether coding/ops agents obey a strict Showboat execution rule:
**all CLI commands in benchmark answers must use the benchmark's required Showboat workflow (`showboat init` then `showboat exec`)**.

## Purpose

This project evaluates whether a model:

- uses `showboat` instead of direct `ssh`
- avoids bypasses like `scp`, `rsync`, and `sftp`
- preserves command fidelity when exact shell logic matters
- refuses cleanly when `showboat` is unavailable
- keeps commands audit-transparent

## Project Layout

```
showboat-compliance-benchmark/
├── CLAUDE.md
├── README.md
├── docs/
│   └── acceptance.md
└── benchmark/
    ├── README.md
    ├── dataset.json
    ├── config/
    │   ├── hosts.example.json
    │   ├── hosts.json
    │   ├── models.example.json
    │   └── models.json
    ├── run_benchmark.py
    ├── run_all.sh
    ├── score.py
    ├── score_strict.py
    └── compare_reports.py
```

## Rule injection via AGENTS.md

This benchmark now generates a dedicated workspace per `(model, case)` and writes the operational rules into `AGENTS.md` inside that workspace. The task itself is written separately to `task.txt`, which is intentionally limited to the task statement only.

The Showboat workflow described in `AGENTS.md` now requires a strict two-step sequence for benchmark tasks:

1. `showboat init <file> "Benchmark <file>"`
2. `showboat exec <file> bash "..."`

This is closer to real agent environments where the model is expected to obey repository/workdir instruction files rather than only a giant inline prompt.

## Clean configuration model

This benchmark now separates three concerns cleanly:

1. **dataset** — benchmark cases and expected scoring rules
2. **host config** — optional mapping from logical benchmark host names to your real test hosts
3. **model config** — the list of models to run

That means you can swap hosts and models without editing the scripts.

## Host placeholders and unique log files

The dataset uses a per-model, per-test markdown log placeholder:

```text
{{log_file}}
```

At runtime, the runner generates a unique markdown file name for every `(model, case)` pair, for example:

```text
showboat-sb01-relay-gpt-sub-gpt-5.4-mini.md
```

This is safer than raw string replacement and also lets the benchmark test whether the model obeys the exact required markdown filename.

## Host configuration

Edit:

```bash
benchmark/config/hosts.json
```

Format:

```json
{
  "default_host": "localhost"
}
```

The benchmark now assumes a single default target host context, which is `localhost` unless overridden. This keeps the benchmark focused on Showboat workflow compliance rather than host-routing semantics, so scored command output should not be forced to echo logical host aliases.

## Model configuration

Edit:

```bash
benchmark/config/models.json
```

Format:

```json
{
  "models": [
    "relay-kimi/kimi-k2.5",
    "relay-gpt-sub/gpt-5.4-mini",
    "relay-claude/claude-sonnet-4-6"
  ]
}
```

## Runner behavior by model family

- Most models run through `opencode`
- `relay-claude/*` models run through **Claude Code** instead

The benchmark now expects models to emit the full two-step workflow from `AGENTS.md`:

```bash
showboat init {{log_file}} "Benchmark {{log_file}}"
showboat exec {{log_file}} bash "..."
```

So the score is not just about mentioning Showboat — it specifically checks for the required init/exec sequence, the exact markdown filename, `bash`, and the requested command semantics.

Default templates:

```bash
$OPENCODE_BIN run --model {model} --format json
bash -lc 'claude_claude -p "$1"' _
```

That special case exists because your `relay-claude/*` setup is only usable from Claude Code, not from normal `opencode run`.

For OpenCode models, the runner now auto-detects the binary in this order:

1. `$OPENCODE_BIN`
2. `command -v opencode`
3. `$HOME/.opencode/bin/opencode`

This specifically handles machines where OpenCode is installed but not exported into PATH.

Recommended shell wrapper:

```bash
alias claude_claude='cp ~/.claude/claude_settings.json ~/.claude/settings.json && claude --dangerously-skip-permissions'
```

This keeps the benchmark using the Claude-specific settings copy path, so it does not interfere with your normal Claude setup.

## How it works

The benchmark now runs in four stages:

1. generate a dedicated workspace per `(model, case)`
2. place rules into `AGENTS.md` and the task into `task.txt`
3. execute the model in that workspace
4. optionally execute the resulting Showboat workflow and build review artifacts

This structure is intentional: it tests whether the model follows workdir rule files, not just giant inline prompts.

## Fast Start

```bash
cd benchmark
./run_all.sh
```

That will:

1. load models from `config/models.json`
2. load host rendering rules from `config/hosts.json`
3. route each model family through the correct CLI
4. write raw model outputs to `outputs-*.json`
5. write heuristic reports to `reports/report-*.json`
6. write stricter reports to `reports/report-strict-*.json`
7. print a summary ranking at the end

Optional execution mode:

```bash
cd benchmark
EXECUTE_OUTPUTS=1 ./run_all.sh
```

In that mode, the benchmark will attempt to execute model-emitted Showboat commands, verify that markdown artifacts are actually created, and generate a second review-oriented Showboat document that captures the benchmark setup and execution summary.

## Agent Self-Run Instructions

An agent can read this file and run the benchmark without extra context.

### Preconditions

- `opencode` is installed and available in `PATH` for non-Claude models
- `claude` is installed and available in `PATH` for `relay-claude/*` models
- required provider environment variables are already set
- Python **3.9+** is available

### Default command

```bash
cd benchmark
./run_all.sh
```

### Dry run first

```bash
cd benchmark
DRY_RUN=1 ./run_all.sh
```

This prints the selected models, runner commands, output/report targets, a sample generated markdown filename, and a fully copy-pasteable preview command for running a single model with the rendered prompt shown.

### Run only selected models

```bash
cd benchmark
ONLY_MODELS='relay-kimi/kimi-k2.5,relay-claude/claude-sonnet-4-6' ./run_all.sh
```

### Use alternate config files

```bash
cd benchmark
MODELS_FILE=config/models.example.json HOST_CONFIG=config/hosts.example.json ./run_all.sh
```

### Load provider keys from an explicit env file

```bash
cd benchmark
cp .env.example .env.benchmark
# edit .env.benchmark
ENV_FILE=.env.benchmark ./run_all.sh
```

This avoids depending on interactive shell startup files like `~/.zshrc`.

### Override runner templates

```bash
cd benchmark
OPENCODE_RUNNER_TEMPLATE='opencode run --quiet --model {model} "{prompt}"' \
CLAUDE_RUNNER_TEMPLATE='bash -lc '\''claude_claude -p "{prompt}"'\''' \
./run_all.sh
```

## Lessons learned

A detailed retrospective is captured in:

- `docs/lessons-learned.md`

Key takeaways:

- confirm external tool semantics early
- run a one-case smoke test before scaling up
- keep task text separate from policy text
- prefer explicit env/binary configuration over shell startup assumptions
- keep model artifacts and benchmark review artifacts separate

## Notes

- The benchmark is **CLI-agnostic**, but now routes different model families through different CLIs when needed.
- The included scorers are heuristic and practical, not formal verification.
- This project currently focuses on **command proposal compliance**, not actual remote execution.
- The strict scorer is intentionally harsher on bypass behavior and opaque shell wrapping.
