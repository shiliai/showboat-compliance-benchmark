# Lessons Learned — showboat-compliance-benchmark

## What we learned

### 1. Confirm tool semantics early
At first the benchmark design drifted because `showboat` was treated too much like a remote-execution proxy instead of a command/output logging tool.

The useful correction was:

- the benchmark should evaluate `showboat init` + `showboat exec`
- the real artifact is the generated markdown document
- the final test should verify both command syntax and markdown output

### 2. Always run a one-case smoke test first
The most effective debugging move was shrinking the problem down to:

- one model
- one case (`SB01`)
- one simple command (`cat /etc/os-release`)
- one expected markdown artifact

That surfaced path, auth, quoting, and parser problems much faster than trying to reason about the full benchmark at once.

### 3. Separate rules from tasks
The benchmark became more realistic after splitting:

- `AGENTS.md` for operational rules and case-specific policy
- `task.txt` for the task only

This better measures model compliance with repository/workdir rules instead of repeating rules inside every prompt.

### 4. Non-interactive runtime assumptions matter
Several issues came from environment differences between interactive shells and benchmark execution:

- `opencode` was installed but not in `PATH`
- provider keys in `~/.zshrc` were not reliably present in non-interactive runs
- `showboat` also lived outside the default PATH

The benchmark now supports explicit configuration for:

- `ENV_FILE`
- `OPENCODE_BIN`
- `SHOWBOAT_BIN`

### 5. OpenCode JSON streams need explicit parsing
`opencode run --format json` emits event streams, not a single clean text result. The benchmark needed custom parsing for `type=text` events and fenced code blocks to extract the actual command output reliably.

### 6. Review artifacts are worth keeping separate
Keeping two documents is clearer than forcing everything into one file:

- `showboat-*.md` — model-generated artifact
- `benchmark-*.md` — benchmark review document

That separation makes it easier to distinguish model behavior from harness behavior.

## Recommended workflow for future changes

1. Confirm the target CLI semantics (`--help`, README, smallest real command)
2. Run one-case smoke test before scaling out
3. Keep task text minimal
4. Put policy in `AGENTS.md` / `CLAUDE.md`
5. Add execution validation only after model output format is stable
6. Capture both model artifact and benchmark review artifact

## Practical checklist for future debugging

- Is the correct binary available (`opencode`, `showboat`, `claude`)?
- Are provider keys available in the execution environment?
- Is the model output parsed into clean command text?
- Does the command match the required Showboat workflow exactly?
- Does execution create the expected markdown artifact?
- Does the review document capture the case files and execution summary?
