#!/usr/bin/env python3
"""
Summarize benchmark effectiveness across models for skill evaluation.

This script:
1. Loads skill content from SKILL.md + references
2. Discovers model slugs from outputs-glob pattern
3. For each model, joins benchmark evidence into per-case review bundles
4. Computes deterministic semantic baseline via score_adjusted.score_case_adjusted()
5. Detects case-id divergence and exits non-zero on mismatch
6. Creates rendering payload for judge prompt and decision payload for aggregation
7. Optionally invokes a review model (judge) for each case
8. Persists prompt/response traces for auditing
"""

import argparse
import glob
import json
import re
import shlex
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Set


def load_json(path: Path) -> Any:
    """Load JSON from file."""
    return json.loads(path.read_text(encoding="utf-8"))


def save_json(path: Path, data: Any) -> None:
    """Save JSON to file with pretty formatting."""
    path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def run_command(
    cmd: List[str], timeout: int, cwd: Path
) -> subprocess.CompletedProcess[Any]:
    try:
        return subprocess.run(
            cmd, text=True, capture_output=True, timeout=timeout, cwd=str(cwd)
        )
    except subprocess.TimeoutExpired as e:
        return subprocess.CompletedProcess(
            args=e.cmd,
            returncode=-1,
            stdout=e.stdout.decode("utf-8") if e.stdout else "",
            stderr=e.stderr.decode("utf-8") if e.stderr else "",
        )


def strip_fences(text: str) -> str:
    """Remove markdown code fences from text."""
    stripped = text.strip()
    fence_match = re.match(r"^```(?:[a-zA-Z0-9_-]+)?\n([\s\S]*?)\n```$", stripped)
    if fence_match:
        return fence_match.group(1).strip()
    return stripped


def extract_from_json_stream(text: str) -> Optional[str]:
    """Extract text content from NDJSON stream output."""
    chunks = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            item = json.loads(line)
        except Exception:
            continue
        if not isinstance(item, dict):
            continue
        if item.get("type") == "text":
            part = item.get("part", {})
            value = part.get("text")
            if isinstance(value, str) and value.strip():
                chunks.append(strip_fences(value))
        elif item.get("type") == "result":
            value = item.get("text") or item.get("output") or item.get("content")
            if isinstance(value, str) and value.strip():
                chunks.append(strip_fences(value))
    if chunks:
        return "\n".join(chunks).strip()
    return None


def default_adapter(stdout: str, stderr: str, returncode: int) -> str:
    """Normalize command output, handling JSON streams and code fences."""
    text = stdout.strip()
    if text:
        extracted = extract_from_json_stream(text)
        if extracted:
            return extracted
        return strip_fences(text)
    if stderr.strip():
        return stderr.strip()
    return f"<empty output, returncode={returncode}>"


def parse_json_response(text: str) -> Optional[Dict[str, Any]]:
    """
    Parse JSON from response text, handling fenced JSON and JSON streams.

    Returns parsed dict or None if parsing fails.
    """
    # Try JSON stream extraction first
    extracted = extract_from_json_stream(text)
    if extracted:
        try:
            return json.loads(extracted)
        except json.JSONDecodeError:
            pass

    # Try fenced JSON
    stripped = strip_fences(text)
    try:
        return json.loads(stripped)
    except json.JSONDecodeError:
        pass

    # Try raw text as JSON
    try:
        return json.loads(text.strip())
    except json.JSONDecodeError:
        return None


def invoke_judge(
    runner_template: str,
    model: str,
    prompt: str,
    timeout: int,
    cwd: Path,
) -> Dict[str, Any]:
    """
    Invoke a judge model using the runner template.

    Returns a dict with:
    - stdout: raw stdout
    - stderr: raw stderr
    - returncode: process return code (-1 for timeout)
    - parsed_response: parsed JSON response or None
    - normalized_output: normalized text output
    - timeout_occurred: bool
    """
    # Build command from template
    cmd = shlex.split(runner_template)
    # Replace {model} placeholder if present
    cmd = [c.replace("{model}", model) for c in cmd]
    # Append prompt as final argument
    cmd.append(prompt)

    # Run the command
    result = run_command(cmd, timeout=timeout, cwd=cwd)

    timeout_occurred = result.returncode == -1
    normalized = default_adapter(result.stdout, result.stderr, result.returncode)
    parsed = parse_json_response(normalized) if not timeout_occurred else None

    return {
        "stdout": result.stdout,
        "stderr": result.stderr,
        "returncode": result.returncode,
        "normalized_output": normalized,
        "parsed_response": parsed,
        "timeout_occurred": timeout_occurred,
    }


def load_skill_content(skill_path: Path) -> str:
    """Load skill instructions from SKILL.md and all reference files."""
    skill_md = skill_path / "SKILL.md"
    if not skill_md.exists():
        raise FileNotFoundError(f"SKILL.md not found at {skill_path}")

    content_parts = [skill_md.read_text(encoding="utf-8")]

    # Load all reference files
    references_dir = skill_path / "references"
    if references_dir.exists():
        for ref_file in sorted(references_dir.glob("*.md")):
            ref_content = ref_file.read_text(encoding="utf-8")
            content_parts.append(
                f"\n\n---\n\n## Reference: {ref_file.name}\n\n{ref_content}"
            )

    return "\n".join(content_parts)


def discover_model_slugs(outputs_glob: str, benchmark_dir: Path) -> List[str]:
    """
    Discover model slugs from outputs glob pattern.

    Extracts model slug from filenames like outputs-<slug>.json
    """
    full_pattern = str(benchmark_dir / outputs_glob)
    matching_files = glob.glob(full_pattern)

    slugs = []
    for filepath in matching_files:
        filename = Path(filepath).name
        # Extract slug from outputs-<slug>.json pattern
        if filename.startswith("outputs-") and filename.endswith(".json"):
            # Handle outputs-slug.json and outputs-slug.json.meta.json
            remainder = filename[len("outputs-") :]
            # Remove .json suffix (and any .meta.json suffix)
            if remainder.endswith(".meta.json"):
                continue  # Skip meta files
            if remainder.endswith(".json"):
                slug = remainder[:-5]  # Remove .json
                if slug and slug not in slugs:
                    slugs.append(slug)

    return sorted(slugs)


def resolve_source_files(
    benchmark_dir: Path, model_slug: str, reports_dir: Path
) -> Dict[str, Optional[Path]]:
    """
    Resolve source files for the given model slug.

    Returns dict mapping logical names to file paths (or None if not found).
    """
    sources = {}

    # Required: outputs JSON and its metadata
    outputs_file = benchmark_dir / f"outputs-{model_slug}.json"
    sources["outputs"] = outputs_file if outputs_file.exists() else None

    outputs_meta = benchmark_dir / f"outputs-{model_slug}.json.meta.json"
    sources["outputs_meta"] = outputs_meta if outputs_meta.exists() else None

    # Required: strict report
    strict_report = reports_dir / f"report-strict-{model_slug}.json"
    sources["strict_report"] = strict_report if strict_report.exists() else None

    # Optional: heuristic report
    report_file = reports_dir / f"report-{model_slug}.json"
    sources["report"] = report_file if report_file.exists() else None

    # Optional: adjusted report
    adjusted_report = reports_dir / f"report-adjusted-{model_slug}.json"
    sources["adjusted_report"] = adjusted_report if adjusted_report.exists() else None

    # Optional: execute report
    execute_report = reports_dir / f"execute-{model_slug}.json"
    sources["execute_report"] = execute_report if execute_report.exists() else None

    return sources


def build_case_bundles(
    dataset: List[Dict[str, Any]],
    outputs: Dict[str, str],
    outputs_meta: Dict[str, Any],
    strict_results: List[Dict[str, Any]],
    heuristic_results: Optional[List[Dict[str, Any]]],
    adjusted_results: Optional[List[Dict[str, Any]]],
    execute_results: Optional[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """
    Build per-case review bundles joining all evidence.

    Each bundle includes:
    - case_id
    - category
    - task (description)
    - expected rules
    - raw output
    - strict result
    - heuristic result (if available)
    - adjusted baseline (computed via score_adjusted)
     - execution evidence (if available)
    """
    # Import score_adjusted for baseline computation
    import importlib.util
    import os

    _script_dir = os.path.dirname(os.path.abspath(__file__))
    _score_adjusted_path = os.path.join(_script_dir, "score_adjusted.py")
    _spec = importlib.util.spec_from_file_location(
        "score_adjusted", _score_adjusted_path
    )
    if _spec is None or _spec.loader is None:
        raise ImportError(f"Could not load score_adjusted from {_score_adjusted_path}")
    score_adjusted_module = importlib.util.module_from_spec(_spec)
    _spec.loader.exec_module(score_adjusted_module)

    # Index results by case ID
    strict_by_id = {r["id"]: r for r in strict_results}
    heuristic_by_id = (
        {r["id"]: r for r in heuristic_results} if heuristic_results else {}
    )
    adjusted_by_id = {r["id"]: r for r in adjusted_results} if adjusted_results else {}

    # Index execution results by case ID
    execute_by_id = {}
    if execute_results and "results" in execute_results:
        execute_by_id = {r["id"]: r for r in execute_results["results"]}

    # Build metadata lookup
    meta_cases = {}
    if outputs_meta and "cases" in outputs_meta:
        for case_info in outputs_meta["cases"]:
            meta_cases[case_info["id"]] = case_info

    bundles = []
    for case in dataset:
        case_id = case["id"]
        output = outputs.get(case_id, "")
        meta_case = meta_cases.get(case_id)

        # Compute deterministic semantic baseline
        baseline = score_adjusted_module.score_case_adjusted(case, output, meta_case)

        bundle = {
            "case_id": case_id,
            "category": case.get("category", "unknown"),
            "task": case.get("task", ""),
            "expected": case.get("expected", {}),
            "raw_output": output,
            "strict_result": strict_by_id.get(case_id),
            "heuristic_result": heuristic_by_id.get(case_id),
            "adjusted_baseline": baseline,
            "execution_evidence": execute_by_id.get(case_id),
        }
        bundles.append(bundle)

    return bundles


def detect_case_divergence(
    dataset_ids: Set[str],
    strict_ids: Set[str],
    model_slug: str,
) -> Optional[str]:
    """
    Detect case-id divergence between dataset and reports.

    Returns error message if divergence detected, None if all match.
    """
    missing_in_strict = dataset_ids - strict_ids
    extra_in_strict = strict_ids - dataset_ids

    if missing_in_strict or extra_in_strict:
        parts = []
        if missing_in_strict:
            parts.append(
                f"cases in dataset but missing from strict report: {sorted(missing_in_strict)}"
            )
        if extra_in_strict:
            parts.append(
                f"cases in strict report but not in dataset: {sorted(extra_in_strict)}"
            )
        return f"Case-id divergence for model {model_slug}: " + "; ".join(parts)

    return None


def render_judge_prompt(
    skill_content: str,
    case_bundle: Dict[str, Any],
) -> str:
    """
    Render the judge prompt for a single case.

    Includes skill instructions, task text, expected rules, raw output,
    and scoring results.
    """
    lines = [
        "# Benchmark Case Review",
        "",
        "## Skill Instructions",
        "",
        skill_content,
        "",
        "---",
        "",
        f"## Case: {case_bundle['case_id']} ({case_bundle['category']})",
        "",
        "### Task",
        "",
        case_bundle["task"],
        "",
        "### Expected Rules",
        "",
    ]

    expected = case_bundle.get("expected", {})
    if expected:
        lines.append("```json")
        lines.append(json.dumps(expected, indent=2))
        lines.append("```")
    else:
        lines.append("*No explicit rules specified.*")

    lines.extend(
        [
            "",
            "### Model Output",
            "",
            "```",
            case_bundle["raw_output"],
            "```",
            "",
            "### Strict Scoring Result",
            "",
        ]
    )

    strict = case_bundle.get("strict_result")
    if strict:
        lines.append("```json")
        lines.append(json.dumps(strict, indent=2))
        lines.append("```")
    else:
        lines.append("*No strict scoring available.*")

    lines.extend(
        [
            "",
            "### Heuristic Scoring Result",
            "",
        ]
    )

    heuristic = case_bundle.get("heuristic_result")
    if heuristic:
        lines.append("```json")
        lines.append(json.dumps(heuristic, indent=2))
        lines.append("```")
    else:
        lines.append("*No heuristic scoring available.*")

    lines.extend(
        [
            "",
            "### Adjusted Baseline (Deterministic Semantic)",
            "",
        ]
    )

    baseline = case_bundle.get("adjusted_baseline")
    if baseline:
        lines.append("```json")
        lines.append(json.dumps(baseline, indent=2))
        lines.append("```")

    # Execution evidence
    lines.extend(
        [
            "",
            "### Execution Evidence",
            "",
        ]
    )

    exec_evidence = case_bundle.get("execution_evidence")
    if exec_evidence:
        lines.append("```json")
        lines.append(json.dumps(exec_evidence, indent=2))
        lines.append("```")
    else:
        lines.append("*Execution evidence unavailable (execution report not present).*")

    return "\n".join(lines)


def build_aggregation_payload(
    model_slug: str,
    case_bundles: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """
    Build decision payload for aggregation.

    Contains summary statistics and per-case adjusted baseline results.
    """
    total_cases = len(case_bundles)
    passed_cases = 0
    total_score = 0
    max_score = 0
    by_category: Dict[str, Dict[str, int]] = {}

    for bundle in case_bundles:
        baseline = bundle.get("adjusted_baseline", {})
        score = baseline.get("score", 0)
        case_max = baseline.get("max_score", 10)
        passed = baseline.get("passed", False)

        total_score += score
        max_score += case_max
        if passed:
            passed_cases += 1

        category = bundle.get("category", "unknown")
        if category not in by_category:
            by_category[category] = {
                "passed": 0,
                "total": 0,
                "score": 0,
                "max_score": 0,
            }
        by_category[category]["total"] += 1
        by_category[category]["score"] += score
        by_category[category]["max_score"] += case_max
        if passed:
            by_category[category]["passed"] += 1

    return {
        "model_slug": model_slug,
        "summary": {
            "score": total_score,
            "max_score": max_score,
            "percent": round(100 * total_score / max_score, 1) if max_score > 0 else 0,
            "passed_cases": passed_cases,
            "total_cases": total_cases,
        },
        "by_category": by_category,
        "cases": [
            {
                "case_id": b["case_id"],
                "category": b["category"],
                "baseline": b["adjusted_baseline"],
            }
            for b in case_bundles
        ],
    }


def generate_markdown_summary(
    model_summaries: List[Dict[str, Any]],
    skill_path: Path,
) -> str:
    """Generate human-readable markdown summary of effectiveness."""
    lines = [
        "# Benchmark Effectiveness Summary",
        "",
        f"- **Skill Path**: {skill_path}",
        f"- **Models Evaluated**: {len(model_summaries)}",
        "",
        "## Model Rankings (by Adjusted Baseline)",
        "",
        "| Model | Score | Max | Percent | Passed | Total |",
        "|-------|-------|-----|---------|--------|-------|",
    ]

    # Sort by percent descending
    sorted_summaries = sorted(
        model_summaries,
        key=lambda x: x["summary"]["percent"],
        reverse=True,
    )

    for summary in sorted_summaries:
        s = summary["summary"]
        lines.append(
            f"| {summary['model_slug']} | {s['score']} | {s['max_score']} | "
            f"{s['percent']}% | {s['passed_cases']} | {s['total_cases']} |"
        )

    # Add category breakdown
    lines.extend(
        [
            "",
            "## Category Breakdown",
            "",
        ]
    )

    # Collect all categories
    all_categories: Set[str] = set()
    for summary in model_summaries:
        all_categories.update(summary["by_category"].keys())

    for category in sorted(all_categories):
        lines.append(f"### {category}")
        lines.append("")
        lines.append("| Model | Score | Max | Percent | Passed | Total |")
        lines.append("|-------|-------|-----|---------|--------|-------|")

        for summary in sorted_summaries:
            if category in summary["by_category"]:
                cat = summary["by_category"][category]
                cat_pct = (
                    round(100 * cat["score"] / cat["max_score"], 1)
                    if cat["max_score"] > 0
                    else 0
                )
                lines.append(
                    f"| {summary['model_slug']} | {cat['score']} | {cat['max_score']} | "
                    f"{cat_pct}% | {cat['passed']} | {cat['total']} |"
                )
        lines.append("")

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(
        description="Summarize benchmark effectiveness across models for skill evaluation"
    )
    parser.add_argument(
        "--dataset",
        required=True,
        help="Path to dataset.json containing benchmark cases",
    )
    parser.add_argument(
        "--reports-dir",
        required=True,
        help="Directory containing report-*.json files",
    )
    parser.add_argument(
        "--outputs-glob",
        required=True,
        help="Glob pattern for outputs-*.json files (e.g., 'outputs-*.json')",
    )
    parser.add_argument(
        "--skill-path",
        required=True,
        help="Path to skill directory containing SKILL.md and references/",
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
        "--timeout",
        type=int,
        default=300,
        help="Timeout in seconds for review operations (default: 300)",
    )
    parser.add_argument(
        "--artifacts-dir",
        required=True,
        help="Directory for prompt/response traces",
    )
    parser.add_argument(
        "--output-markdown",
        required=True,
        help="Path for final markdown summary output",
    )
    parser.add_argument(
        "--invoke-judge",
        action="store_true",
        help="Actually invoke the review model (default: only generate prompts)",
    )
    args = parser.parse_args()

    # Validate inputs
    dataset_path = Path(args.dataset)
    if not dataset_path.exists():
        print(f"ERROR: Dataset file does not exist: {dataset_path}", file=sys.stderr)
        sys.exit(1)

    reports_dir = Path(args.reports_dir)
    if not reports_dir.exists():
        print(
            f"ERROR: Reports directory does not exist: {reports_dir}", file=sys.stderr
        )
        sys.exit(1)

    skill_path = Path(args.skill_path)
    if not skill_path.exists():
        print(f"ERROR: Skill path does not exist: {skill_path}", file=sys.stderr)
        sys.exit(1)

    skill_md = skill_path / "SKILL.md"
    if not skill_md.exists():
        print(f"ERROR: SKILL.md not found in skill path: {skill_md}", file=sys.stderr)
        sys.exit(1)

    artifacts_dir = Path(args.artifacts_dir)
    artifacts_dir.mkdir(parents=True, exist_ok=True)

    # Load dataset
    dataset = load_json(dataset_path)
    dataset_ids = {case["id"] for case in dataset}

    print(f"=== Benchmark Effectiveness Summary ===", file=sys.stderr)
    print(f"Dataset: {dataset_path} ({len(dataset)} cases)", file=sys.stderr)
    print(f"Reports dir: {reports_dir}", file=sys.stderr)
    print(f"Skill path: {skill_path}", file=sys.stderr)
    print(f"Review model: {args.review_model}", file=sys.stderr)
    print(file=sys.stderr)

    # Load skill content
    skill_content = load_skill_content(skill_path)
    print(f"Skill content loaded: {len(skill_content)} characters", file=sys.stderr)

    # Discover model slugs
    benchmark_dir = dataset_path.parent
    model_slugs = discover_model_slugs(args.outputs_glob, benchmark_dir)

    if not model_slugs:
        print(
            f"ERROR: No model outputs found matching pattern: {args.outputs_glob}",
            file=sys.stderr,
        )
        sys.exit(1)

    print(f"Discovered models: {model_slugs}", file=sys.stderr)
    print(file=sys.stderr)

    # Process each model
    model_summaries = []

    for model_slug in model_slugs:
        print(f"--- Processing model: {model_slug} ---", file=sys.stderr)

        # Resolve source files
        sources = resolve_source_files(benchmark_dir, model_slug, reports_dir)

        # Check required sources
        if sources["outputs"] is None:
            print(
                f"  WARNING: outputs file not found for {model_slug}, skipping",
                file=sys.stderr,
            )
            continue
        if sources["strict_report"] is None:
            print(
                f"  WARNING: strict report not found for {model_slug}, skipping",
                file=sys.stderr,
            )
            continue

        # Load outputs
        outputs = load_json(sources["outputs"])

        # Load metadata
        outputs_meta = {}
        if sources["outputs_meta"]:
            outputs_meta = load_json(sources["outputs_meta"])

        # Load strict report
        strict_report = load_json(sources["strict_report"])
        strict_results = strict_report.get("results", [])
        strict_ids = {r["id"] for r in strict_results}

        # Check case-id divergence
        divergence_error = detect_case_divergence(dataset_ids, strict_ids, model_slug)
        if divergence_error:
            print(f"ERROR: {divergence_error}", file=sys.stderr)
            sys.exit(1)

        # Load optional reports
        heuristic_results = None
        if sources["report"]:
            heuristic_report = load_json(sources["report"])
            heuristic_results = heuristic_report.get("results")

        adjusted_results = None
        if sources["adjusted_report"]:
            adjusted_report = load_json(sources["adjusted_report"])
            adjusted_results = adjusted_report.get("results")

        execute_results = None
        if sources["execute_report"]:
            execute_results = load_json(sources["execute_report"])

        # Build case bundles
        case_bundles = build_case_bundles(
            dataset=dataset,
            outputs=outputs,
            outputs_meta=outputs_meta,
            strict_results=strict_results,
            heuristic_results=heuristic_results,
            adjusted_results=adjusted_results,
            execute_results=execute_results,
        )

        # Save case bundles to artifacts
        bundles_path = artifacts_dir / f"case-bundles-{model_slug}.json"
        save_json(bundles_path, case_bundles)
        print(f"  Case bundles saved: {bundles_path}", file=sys.stderr)

        # Render judge prompts and save
        prompts_dir = artifacts_dir / "judge-prompts" / model_slug
        prompts_dir.mkdir(parents=True, exist_ok=True)

        # Create review trace directory for this model
        review_dir = artifacts_dir / "review" / model_slug
        review_dir.mkdir(parents=True, exist_ok=True)

        review_results: List[Dict[str, Any]] = []

        for bundle in case_bundles:
            case_id = bundle["case_id"]
            prompt = render_judge_prompt(skill_content, bundle)

            # Save prompt file
            prompt_path = prompts_dir / f"{case_id}.md"
            prompt_path.write_text(prompt, encoding="utf-8")

            # Also save to review directory as .prompt.txt
            review_prompt_path = review_dir / f"{case_id}.prompt.txt"
            review_prompt_path.write_text(prompt, encoding="utf-8")

            if args.invoke_judge:
                print(f"    Invoking judge for case: {case_id}", file=sys.stderr)
                judge_result = invoke_judge(
                    runner_template=args.review_runner,
                    model=args.review_model,
                    prompt=prompt,
                    timeout=args.timeout,
                    cwd=Path.cwd(),
                )

                # Save response trace
                response_path = review_dir / f"{case_id}.response.txt"
                response_path.write_text(
                    judge_result["normalized_output"], encoding="utf-8"
                )

                # Determine decision: parsed JSON or fallback to strict result
                decision: Dict[str, Any]
                if judge_result["timeout_occurred"]:
                    print(
                        f"    WARNING: Judge timeout for {case_id}, falling back to strict result",
                        file=sys.stderr,
                    )
                    decision = {
                        "verdict": "timeout",
                        "case_id": case_id,
                        "fallback": True,
                        "strict_result": bundle.get("strict_result"),
                        "adjusted_baseline": bundle.get("adjusted_baseline"),
                    }
                elif judge_result["parsed_response"] is None:
                    print(
                        f"    WARNING: Failed to parse judge response for {case_id}, falling back to strict result",
                        file=sys.stderr,
                    )
                    decision = {
                        "verdict": "parse_error",
                        "case_id": case_id,
                        "fallback": True,
                        "raw_output": judge_result["normalized_output"][:500],
                        "strict_result": bundle.get("strict_result"),
                        "adjusted_baseline": bundle.get("adjusted_baseline"),
                    }
                else:
                    decision = judge_result["parsed_response"]
                    decision["case_id"] = case_id
                    decision["fallback"] = False

                # Save decision JSON
                decision_path = review_dir / f"{case_id}.decision.json"
                save_json(decision_path, decision)

                review_results.append(
                    {
                        "case_id": case_id,
                        "returncode": judge_result["returncode"],
                        "timeout": judge_result["timeout_occurred"],
                        "parsed": judge_result["parsed_response"] is not None,
                        "fallback": decision.get("fallback", False),
                    }
                )
            else:
                # Not invoking judge, just note that prompt was generated
                review_results.append(
                    {
                        "case_id": case_id,
                        "prompt_generated": True,
                        "judge_invoked": False,
                    }
                )

        print(f"  Judge prompts saved: {prompts_dir}", file=sys.stderr)
        if args.invoke_judge:
            print(f"  Review traces saved: {review_dir}", file=sys.stderr)

        # Save review results summary
        review_summary_path = review_dir / "review-summary.json"
        save_json(
            review_summary_path,
            {
                "model_slug": model_slug,
                "review_model": args.review_model,
                "invoke_judge": args.invoke_judge,
                "cases": review_results,
            },
        )

        # Build aggregation payload
        agg_payload = build_aggregation_payload(model_slug, case_bundles)
        model_summaries.append(agg_payload)

        # Save aggregation payload
        agg_path = artifacts_dir / f"aggregation-{model_slug}.json"
        save_json(agg_path, agg_payload)
        print(f"  Aggregation payload saved: {agg_path}", file=sys.stderr)

        # Print summary
        s = agg_payload["summary"]
        print(
            f"  Summary: {s['score']}/{s['max_score']} ({s['percent']}%), {s['passed_cases']}/{s['total_cases']} passed",
            file=sys.stderr,
        )
        print(file=sys.stderr)

    # Generate and save markdown summary
    markdown_summary = generate_markdown_summary(model_summaries, skill_path)
    output_path = Path(args.output_markdown)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(markdown_summary, encoding="utf-8")

    print(f"=== Summary complete ===", file=sys.stderr)
    print(f"Markdown summary saved to: {output_path}", file=sys.stderr)

    # Also save full JSON summary
    json_summary_path = output_path.with_suffix(".json")
    save_json(
        json_summary_path,
        {
            "skill_path": str(skill_path),
            "dataset": str(dataset_path),
            "review_runner": args.review_runner,
            "review_model": args.review_model,
            "models": model_summaries,
        },
    )
    print(f"JSON summary saved to: {json_summary_path}", file=sys.stderr)


if __name__ == "__main__":
    main()
