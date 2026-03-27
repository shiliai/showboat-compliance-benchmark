#!/usr/bin/env python3
"""
Validate the final-effectiveness-summary skill by running evals with and without the skill.

This script runs each eval prompt twice:
1. with_skill: prepend pointer-style instructions that tell the model to read skill files from disk
2. without_skill: run the eval prompt as-is (baseline)

Outputs are written to iteration workspace directories with metadata and timing info.
"""

import argparse
import json
import shlex
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

try:
    from benchmark._utils import default_adapter, load_json, run_command, save_json
except ImportError:
    import importlib

    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    _utils = importlib.import_module("benchmark._utils")
    default_adapter = _utils.default_adapter
    load_json = _utils.load_json
    run_command = _utils.run_command
    save_json = _utils.save_json


def resolve_source_files(
    benchmark_dir: Path, model_slug: str
) -> Dict[str, Optional[Path]]:
    """
    Resolve source files for the given model slug from benchmark directory.

    Returns dict mapping logical names to file paths (or None if not found).
    """
    sources = {}

    # Required: outputs JSON and its metadata
    outputs_file = benchmark_dir / f"outputs-{model_slug}.json"
    sources["outputs"] = outputs_file if outputs_file.exists() else None

    outputs_meta = benchmark_dir / f"outputs-{model_slug}.json.meta.json"
    sources["outputs_meta"] = outputs_meta if outputs_meta.exists() else None

    # Reports directory
    reports_dir = benchmark_dir / "reports"

    # Required: report files
    report_file = reports_dir / f"report-{model_slug}.json"
    sources["report"] = report_file if report_file.exists() else None

    strict_report = reports_dir / f"report-strict-{model_slug}.json"
    sources["strict_report"] = strict_report if strict_report.exists() else None

    # Optional: adjusted and execute reports
    adjusted_report = reports_dir / f"report-adjusted-{model_slug}.json"
    sources["adjusted_report"] = adjusted_report if adjusted_report.exists() else None

    execute_report = reports_dir / f"execute-{model_slug}.json"
    sources["execute_report"] = execute_report if execute_report.exists() else None

    # Optional: artifacts directory
    artifact_dir = benchmark_dir / "artifacts" / model_slug
    sources["artifact_dir"] = artifact_dir if artifact_dir.exists() else None

    return sources


def validate_skill_files(skill_path: Path) -> None:
    required_files = [
        skill_path / "SKILL.md",
        skill_path / "references" / "review-rubric.md",
        skill_path / "references" / "response-schema.md",
    ]
    missing_files = [str(path) for path in required_files if not path.exists()]
    if missing_files:
        raise FileNotFoundError(
            "Missing required skill files: " + ", ".join(sorted(missing_files))
        )


def build_prompt_with_skill(eval_prompt: str, skill_path: Path) -> str:
    abs_skill = skill_path.resolve()
    return f"""## Skill Instructions

Before answering this evaluation, read the skill files from disk:
1. `{abs_skill}/SKILL.md`
2. `{abs_skill}/references/review-rubric.md`
3. `{abs_skill}/references/response-schema.md`

Follow those files exactly.

---

## Evaluation Task

{eval_prompt}"""


def format_runtime_path(path: Optional[Path]) -> str:
    return str(path) if path is not None else "<not available>"


def render_eval_prompt(
    eval_prompt: str,
    benchmark_dir: Path,
    model_slug: str,
    source_files: Dict[str, Optional[Path]],
) -> str:
    replacements = {
        "{benchmark_dir}": str(benchmark_dir),
        "{model_slug}": model_slug,
        "{outputs}": format_runtime_path(source_files.get("outputs")),
        "{report}": format_runtime_path(source_files.get("report")),
        "{strict_report}": format_runtime_path(source_files.get("strict_report")),
        "{adjusted_report}": format_runtime_path(source_files.get("adjusted_report")),
        "{execute_report}": format_runtime_path(source_files.get("execute_report")),
        "{artifact_dir}": format_runtime_path(source_files.get("artifact_dir")),
    }
    rendered = eval_prompt
    for placeholder, value in replacements.items():
        rendered = rendered.replace(placeholder, value)
    return rendered


def extract_tokens_from_output(stdout: str) -> Optional[int]:
    """
    Try to extract token count from runner output.
    Returns None if not available.
    """
    # Try JSON stream format first
    for line in stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            item = json.loads(line)
        except Exception:
            continue
        if not isinstance(item, dict):
            continue
        # Look for token usage in various formats
        usage = item.get("usage", {})
        if usage:
            return usage.get("total_tokens") or usage.get("total")
        # Some runners report tokens at result level
        if item.get("type") == "result":
            tokens = item.get("tokens") or item.get("total_tokens")
            if tokens:
                return tokens
    return None


def run_eval(
    runner_cmd: str,
    model: str,
    prompt: str,
    timeout: int,
    cwd: Path,
) -> Dict[str, Any]:
    """
    Run a single evaluation.

    Returns dict with:
    - output: the normalized output text
    - duration_ms: execution time in milliseconds
    - total_tokens: token count if available, else None
    - returncode: process return code
    - raw_stdout: raw stdout for debugging
    - raw_stderr: raw stderr for debugging
    """
    # Build command
    cmd = shlex.split(runner_cmd)
    # Append model if template has {model} placeholder, otherwise assume it's in the template
    cmd_str = " ".join(shlex.quote(c) for c in cmd)
    if "{model}" in cmd_str:
        cmd = [c.replace("{model}", model) for c in cmd]
    cmd.append(prompt)

    start_time = time.time()
    cp = run_command(cmd, timeout=timeout, cwd=cwd)
    duration_ms = int((time.time() - start_time) * 1000)

    # Extract tokens from stdout
    total_tokens = extract_tokens_from_output(cp.stdout)

    # Normalize output
    if cp.returncode == -1:
        output = f"<timeout after {timeout} seconds>"
    else:
        output = default_adapter(cp.stdout, cp.stderr, cp.returncode)

    return {
        "output": output,
        "duration_ms": duration_ms,
        "total_tokens": total_tokens,
        "returncode": cp.returncode,
        "raw_stdout": cp.stdout,
        "raw_stderr": cp.stderr,
    }


def main():
    parser = argparse.ArgumentParser(
        description="Validate final-effectiveness-summary skill by running evals with and without skill loading"
    )
    parser.add_argument(
        "--skill-path",
        required=True,
        help="Path to the skill directory containing SKILL.md and references/",
    )
    parser.add_argument(
        "--evals",
        required=True,
        help="Path to evals JSON file containing evaluation prompts",
    )
    parser.add_argument(
        "--benchmark-dir",
        required=True,
        help="Path to benchmark directory containing outputs and reports",
    )
    parser.add_argument(
        "--model-slug",
        required=True,
        help="Model slug for resolving source files (e.g., relay-kimi_kimi-k2.5)",
    )
    parser.add_argument(
        "--review-runner",
        required=True,
        help="Runner command template for the review model (e.g., 'opencode run --model {model} --format json')",
    )
    parser.add_argument(
        "--review-model",
        required=True,
        help="Model identifier for the review model (e.g., relay-kimi/kimi-k2.5)",
    )
    parser.add_argument(
        "--workspace",
        required=True,
        help="Base workspace directory for validation outputs",
    )
    parser.add_argument(
        "--iteration",
        type=int,
        required=True,
        help="Iteration number for this validation run",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=300,
        help="Timeout in seconds for each eval run (default: 300)",
    )
    args = parser.parse_args()

    # Validate inputs
    skill_path = Path(args.skill_path)
    if not skill_path.exists():
        print(f"ERROR: Skill path does not exist: {skill_path}", file=sys.stderr)
        sys.exit(1)

    skill_md = skill_path / "SKILL.md"
    if not skill_md.exists():
        print(f"ERROR: SKILL.md not found in skill path: {skill_md}", file=sys.stderr)
        sys.exit(1)

    evals_path = Path(args.evals)
    if not evals_path.exists():
        print(f"ERROR: Evals file does not exist: {evals_path}", file=sys.stderr)
        sys.exit(1)

    benchmark_dir = Path(args.benchmark_dir)
    if not benchmark_dir.exists():
        print(
            f"ERROR: Benchmark directory does not exist: {benchmark_dir}",
            file=sys.stderr,
        )
        sys.exit(1)

    # Resolve source files
    source_files = resolve_source_files(benchmark_dir, args.model_slug)

    # Check required sources
    required_keys = ["outputs", "outputs_meta", "report", "strict_report"]
    missing_required = [k for k in required_keys if source_files.get(k) is None]
    if missing_required:
        print(
            f"ERROR: Missing required source files for model {args.model_slug}: {missing_required}",
            file=sys.stderr,
        )
        sys.exit(1)

    validate_skill_files(skill_path)

    # Load evals
    evals_data = load_json(evals_path)
    evals = evals_data.get("evals", [])
    if not evals:
        print(f"ERROR: No evals found in {evals_path}", file=sys.stderr)
        sys.exit(1)
    if not isinstance(evals, list):
        print(f"ERROR: 'evals' must be a list in {evals_path}", file=sys.stderr)
        sys.exit(1)

    # Setup workspace
    workspace = Path(args.workspace)
    iteration_dir = (
        workspace / "final-effectiveness-summary" / f"iteration-{args.iteration}"
    )
    iteration_dir.mkdir(parents=True, exist_ok=True)

    print(f"=== Skill Validation: iteration {args.iteration} ===", file=sys.stderr)
    print(f"Skill path: {skill_path}", file=sys.stderr)
    print(f"Benchmark dir: {benchmark_dir}", file=sys.stderr)
    print(f"Model slug: {args.model_slug}", file=sys.stderr)
    print(f"Review model: {args.review_model}", file=sys.stderr)
    print(f"Evals count: {len(evals)}", file=sys.stderr)
    print(f"Output dir: {iteration_dir}", file=sys.stderr)
    print(file=sys.stderr)

    # Track results
    results_evals: List[Dict[str, Any]] = []
    results: Dict[str, Any] = {
        "iteration": args.iteration,
        "skill_path": str(skill_path),
        "benchmark_dir": str(benchmark_dir),
        "model_slug": args.model_slug,
        "review_model": args.review_model,
        "source_files": {k: str(v) if v else None for k, v in source_files.items()},
        "evals": results_evals,
    }

    # Run each eval in both modes
    for eval_item in evals:
        eval_id = eval_item.get("id", "unknown")
        eval_prompt = eval_item.get("prompt", "")
        eval_description = eval_item.get("description", "")
        rendered_eval_prompt = render_eval_prompt(
            eval_prompt=eval_prompt,
            benchmark_dir=benchmark_dir,
            model_slug=args.model_slug,
            source_files=source_files,
        )

        print(f"--- Eval: {eval_id} ---", file=sys.stderr)

        eval_dir = iteration_dir / eval_id
        eval_dir.mkdir(parents=True, exist_ok=True)

        eval_result = {
            "id": eval_id,
            "description": eval_description,
            "runs": {},
        }

        for mode in ["with_skill", "without_skill"]:
            mode_dir = eval_dir / mode
            mode_dir.mkdir(parents=True, exist_ok=True)
            outputs_dir = mode_dir / "outputs"
            outputs_dir.mkdir(parents=True, exist_ok=True)

            # Build prompt
            if mode == "with_skill":
                prompt = build_prompt_with_skill(rendered_eval_prompt, skill_path)
            else:
                prompt = rendered_eval_prompt

            print(f"  Running {mode}...", file=sys.stderr)

            # Run evaluation
            run_result = run_eval(
                runner_cmd=args.review_runner,
                model=args.review_model,
                prompt=prompt,
                timeout=args.timeout,
                cwd=benchmark_dir,
            )

            # Save output
            response_path = outputs_dir / "response.txt"
            response_path.write_text(run_result["output"], encoding="utf-8")

            # Write eval metadata
            metadata = {
                "eval_id": eval_id,
                "mode": mode,
                "source_files": {
                    k: str(v) if v else None for k, v in source_files.items()
                },
                "review_model": args.review_model,
                "benchmark_dir": str(benchmark_dir),
            }
            save_json(mode_dir / "eval_metadata.json", metadata)

            # Write timing info
            timing = {
                "duration_ms": run_result["duration_ms"],
                "total_tokens": run_result["total_tokens"],
                "returncode": run_result["returncode"],
            }
            save_json(mode_dir / "timing.json", timing)

            eval_result["runs"][mode] = {
                "output_file": str(response_path),
                "duration_ms": run_result["duration_ms"],
                "total_tokens": run_result["total_tokens"],
                "returncode": run_result["returncode"],
            }

            print(f"    Duration: {run_result['duration_ms']}ms", file=sys.stderr)
            print(f"    Tokens: {run_result['total_tokens']}", file=sys.stderr)

        results_evals.append(eval_result)
        print(file=sys.stderr)

    # Save iteration summary
    save_json(iteration_dir / "benchmark.json", results)

    # Generate human-readable summary
    summary_lines = [
        f"# Skill Validation: Iteration {args.iteration}",
        "",
        f"- **Skill**: {skill_path}",
        f"- **Benchmark**: {benchmark_dir}",
        f"- **Model Slug**: {args.model_slug}",
        f"- **Review Model**: {args.review_model}",
        "",
        "## Evals",
        "",
    ]

    for eval_item in results_evals:
        summary_lines.append(f"### {eval_item['id']}")
        summary_lines.append("")
        summary_lines.append(f"*{eval_item['description']}*")
        summary_lines.append("")
        for mode, run_info in eval_item["runs"].items():
            summary_lines.append(
                f"- **{mode}**: {run_info['duration_ms']}ms, {run_info['total_tokens']} tokens"
            )
        summary_lines.append("")

    (iteration_dir / "benchmark.md").write_text(
        "\n".join(summary_lines), encoding="utf-8"
    )

    print(f"=== Validation complete ===", file=sys.stderr)
    print(f"Results saved to: {iteration_dir}", file=sys.stderr)
    print(str(iteration_dir))


if __name__ == "__main__":
    main()
