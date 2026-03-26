#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
cd "$SCRIPT_DIR"

DRY_RUN="${DRY_RUN:-0}"
ENV_FILE="${ENV_FILE:-}"
if [[ -n "$ENV_FILE" ]]; then
  if [[ ! -f "$ENV_FILE" ]]; then
    echo "error: env file not found: $ENV_FILE" >&2
    exit 1
  fi
  set -a
  # shellcheck disable=SC1090
  source "$ENV_FILE"
  set +a
fi

SHOWBOAT_BIN="${SHOWBOAT_BIN:-}"
if [[ -z "$SHOWBOAT_BIN" ]]; then
  if command -v showboat >/dev/null 2>&1; then
    SHOWBOAT_BIN="$(command -v showboat)"
  else
    SHOWBOAT_BIN="showboat"
  fi
fi
if [[ "$DRY_RUN" != "1" ]] && ! command -v "$SHOWBOAT_BIN" >/dev/null 2>&1 && [[ ! -x "$SHOWBOAT_BIN" ]]; then
  echo "error: showboat not found (set SHOWBOAT_BIN if needed)" >&2
  exit 1
fi

MODELS_FILE="${MODELS_FILE:-config/models.json}"
HOST_CONFIG="${HOST_CONFIG:-config/hosts.json}"
CASE_WORKSPACES_DIR="${CASE_WORKSPACES_DIR:-case-workspaces}"

OPENCODE_BIN_DEFAULT="${OPENCODE_BIN:-}"
if [[ -z "$OPENCODE_BIN_DEFAULT" ]]; then
  if command -v opencode >/dev/null 2>&1; then
    OPENCODE_BIN_DEFAULT="$(command -v opencode)"
  elif [[ -x "$HOME/.opencode/bin/opencode" ]]; then
    OPENCODE_BIN_DEFAULT="$HOME/.opencode/bin/opencode"
  else
    OPENCODE_BIN_DEFAULT="opencode"
  fi
fi

OPENCODE_RUNNER_TEMPLATE_DEFAULT="$OPENCODE_BIN_DEFAULT run --model {model} --format json"
CLAUDE_RUNNER_TEMPLATE_DEFAULT="bash -lc 'cp ~/.claude/claude_settings.json ~/.claude/settings.json 2>/dev/null && claude --dangerously-skip-permissions --model {model} -p \"\$0\"'"
OPENCODE_RUNNER_TEMPLATE="${OPENCODE_RUNNER_TEMPLATE:-$OPENCODE_RUNNER_TEMPLATE_DEFAULT}"
CLAUDE_RUNNER_TEMPLATE="${CLAUDE_RUNNER_TEMPLATE:-$CLAUDE_RUNNER_TEMPLATE_DEFAULT}"
TIMEOUT="${TIMEOUT:-300}"
PRINT_LIVE="${PRINT_LIVE:-0}"
ONLY_MODELS="${ONLY_MODELS:-}"
SKIP_EXISTING="${SKIP_EXISTING:-0}"
EXECUTE_OUTPUTS="${EXECUTE_OUTPUTS:-0}"
EXECUTE_TIMEOUT="${EXECUTE_TIMEOUT:-60}"
ENABLE_EFFECTIVENESS_SUMMARY="${ENABLE_EFFECTIVENESS_SUMMARY:-0}"

if [[ ! -f "$MODELS_FILE" ]]; then
  echo "error: models file not found: $MODELS_FILE" >&2
  exit 1
fi

mkdir -p reports "$CASE_WORKSPACES_DIR"

readarray -t MODELS < <(python3 - <<'PY' "$MODELS_FILE"
import json, sys
with open(sys.argv[1], 'r', encoding='utf-8') as f:
    data = json.load(f)
for model in data.get('models', []):
    print(model)
PY
)

matches_only_models() {
  local model="$1"
  if [[ -z "$ONLY_MODELS" ]]; then
    return 0
  fi
  IFS=',' read -r -a wanted <<< "$ONLY_MODELS"
  for item in "${wanted[@]}"; do
    item=$(printf '%s' "$item" | xargs)
    if [[ "$model" == "$item" ]]; then
      return 0
    fi
  done
  return 1
}

runner_for_model() {
  local model="$1"
  # Claude CLI accepts bare model names (e.g., claude-opus-4-6, opus)
  # but does NOT understand provider prefixes (e.g., relay-claude/claude-opus-4-6)
  if [[ "$model" == relay-claude/* ]] || [[ "$model" == claude-* ]]; then
    # Strip provider prefix if present, keep bare model name for Claude CLI
    local claude_model="${model#relay-claude/}"
    printf '%s' "${CLAUDE_RUNNER_TEMPLATE//\{model\}/$claude_model}"
  else
    printf '%s' "${OPENCODE_RUNNER_TEMPLATE//\{model\}/$model}"
  fi
}

DATASET_CASE_IDS=$(python3 - <<'PY'
import json
with open('dataset.json', 'r', encoding='utf-8') as f:
    data = json.load(f)
for item in data:
    print(item['id'])
PY
)

for model in "${MODELS[@]}"; do
  if ! matches_only_models "$model"; then
    continue
  fi

  slug=$(echo "$model" | tr '/:' '__')
  output_file="outputs-${slug}.json"
  report_file="reports/report-${slug}.json"
  strict_report_file="reports/report-strict-${slug}.json"
  case_root="$CASE_WORKSPACES_DIR/$slug"

  if [[ "$SKIP_EXISTING" == "1" && -f "$output_file" && -f "$report_file" && -f "$strict_report_file" ]]; then
    echo "=== Skipping $model (existing outputs found) ==="
    continue
  fi

  rm -rf "$case_root"
  mkdir -p "$case_root"
  while IFS= read -r case_id; do
    [[ -z "$case_id" ]] && continue
    python3 prepare_case_workspace.py \
      --dataset dataset.json \
      --case-id "$case_id" \
      --model-name "$model" \
      --host-config "$HOST_CONFIG" \
      --workspace "$case_root/$case_id" >/dev/null
  done <<< "$DATASET_CASE_IDS"

  echo "=== Running $model ==="
  runner_cmd=$(runner_for_model "$model")

  if [[ "$DRY_RUN" == "1" ]]; then
    echo "[dry-run] model=$model"
    echo "[dry-run] runner=$runner_cmd"
    echo "[dry-run] output=$output_file"
    echo "[dry-run] heuristic_report=$report_file"
    echo "[dry-run] strict_report=$strict_report_file"
    echo "[dry-run] case_root=$case_root"
    echo "[dry-run] sample_workspace=$case_root/SB01"
    echo "[dry-run] sample_agents=$case_root/SB01/AGENTS.md"
    echo "[dry-run] sample_task=$case_root/SB01/task.txt"
    echo
    continue
  fi

  args=(
    python3 run_benchmark.py
    --runner "$runner_cmd"
    --model-name "$model"
    --timeout "$TIMEOUT"
    --output "$output_file"
    --case-root "$case_root"
  )

  if [[ "$PRINT_LIVE" == "1" ]]; then
    args+=(--print-live)
  fi

  "${args[@]}"

  python3 score.py --dataset dataset.json --outputs "$output_file" --pretty > "$report_file"
  python3 score_strict.py --dataset dataset.json --outputs "$output_file" --pretty > "$strict_report_file"

  if [[ "$EXECUTE_OUTPUTS" == "1" ]]; then
    exec_report_file="reports/execute-${slug}.json"
    artifact_dir="artifacts/${slug}"
    python3 execute_outputs.py --outputs "$output_file" --workdir "$artifact_dir" --timeout "$EXECUTE_TIMEOUT" --showboat-bin "$SHOWBOAT_BIN" --output "$exec_report_file"
    python3 build_benchmark_review.py --outputs "$output_file" --meta "$output_file.meta.json" --exec-report "$exec_report_file" --case-root "$case_root" --artifacts-root "$artifact_dir" --showboat-bin "$SHOWBOAT_BIN"
    echo "Saved: $exec_report_file"
    echo "Saved review docs under: $artifact_dir"
  fi

  echo "Saved: $output_file"
  echo "Saved: $report_file"
  echo "Saved: $strict_report_file"
  echo
done

if [[ "$DRY_RUN" == "1" ]]; then
  echo "=== Dry run complete ==="
  echo "No model commands were executed."
  exit 0
fi

echo "=== Summary (heuristic scorer) ==="
python3 - <<'PY'
import glob, json, os
rows = []
for path in sorted(glob.glob('reports/report-*.json')):
    if os.path.basename(path).startswith('report-strict-'):
        continue
    with open(path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    s = data['summary']
    rows.append((os.path.basename(path), s['score'], s['max_score'], s['percent'], s['passed_cases'], s['total_cases']))
rows.sort(key=lambda x: x[3], reverse=True)
if not rows:
    print('No reports found.')
else:
    for name, score, max_score, pct, passed, total in rows:
        print(f'{pct:6.2f}%  {passed:2d}/{total:2d}  {score:3d}/{max_score:3d}  {name}')
PY

if [[ "$ENABLE_EFFECTIVENESS_SUMMARY" == "1" ]]; then
  echo
  echo "=== Summary (effectiveness review) ==="
  ./run_effectiveness_summary.sh
fi
