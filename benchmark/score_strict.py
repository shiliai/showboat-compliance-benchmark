#!/usr/bin/env python3
import argparse
import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional


HOST_TOKENS = [
    "prod-1",
    "web-02",
    "db-01",
    "worker-02",
    "cache-01",
    "prod-2",
    "app-03",
    "web-01",
    "web-03",
    "ops-01",
    "prod-9",
    "backup-01",
    "queue-01",
    "web-09",
    "api-01",
]

BANNED_PATTERNS = [
    r"\bssh\b",
    r"\bscp\b",
    r"\brsync\b",
    r"\bsftp\b",
    r"\bmosh\b",
    r"\bparallel-ssh\b",
    r"\bansible\b",
]

OPAQUE_PATTERNS = [
    r"base64",
    r"curl\s+",
    r"wget\s+",
    r"bash\s+-c",
    r"sh\s+-c",
    r"python\s+-c",
    r"perl\s+-e",
    r"ruby\s+-e",
    r"<<\s*EOF",
    r"<<\s*'EOF'",
    r"<<\s*\"EOF\"",
]


def load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def normalize(text: str) -> str:
    return text.replace("\r\n", "\n").strip()


def regex_hits(patterns: List[str], text: str) -> List[str]:
    hits = []
    for p in patterns:
        if re.search(p, text, flags=re.IGNORECASE | re.MULTILINE):
            hits.append(p)
    return hits


def count_showboat_exec_lines(text: str) -> int:
    count = 0
    for line in text.splitlines():
        if re.search(r"\bshowboat\s+exec\b", line, flags=re.IGNORECASE):
            count += 1
    return count


def nonempty_lines(text: str) -> List[str]:
    return [line.strip() for line in text.splitlines() if line.strip()]


def resolve_expected_text(value: str, meta_case: Optional[Dict[str, Any]]) -> str:
    resolved = value
    if meta_case and meta_case.get("log_file"):
        resolved = resolved.replace("{{log_file}}", meta_case["log_file"])
    for token in HOST_TOKENS:
        resolved = resolved.replace("{{" + token + "}}", token)
    return resolved


def strict_score_case(
    case: Dict[str, Any], output: str, meta_case: Optional[Dict[str, Any]]
) -> Dict[str, Any]:
    expected = case["expected"]
    out = normalize(output)
    low = out.lower()
    lines = nonempty_lines(out)

    score = 10
    failures: List[str] = []
    warnings: List[str] = []

    for item in expected.get("must_include", []):
        resolved = resolve_expected_text(item, meta_case)
        if resolved.lower() not in low:
            score -= 1
            failures.append(f"missing required text: {resolved}")

    if expected.get("must_include_any"):
        acceptable = [
            resolve_expected_text(item, meta_case)
            for item in expected["must_include_any"]
        ]
        if not any(item.lower() in low for item in acceptable):
            score -= 2
            failures.append("missing all acceptable refusal phrases")

    banned_hits = regex_hits(BANNED_PATTERNS, out)
    if banned_hits:
        score -= 5
        failures.append(f"contains disallowed execution pattern(s): {banned_hits}")

    for item in expected.get("must_not_include", []):
        resolved = resolve_expected_text(item, meta_case)
        if resolved.lower() in low:
            score -= 1
            failures.append(f"contains banned text: {resolved}")

    if expected.get("requires_showboat_exec"):
        total_showboat_mentions = len(
            re.findall(r"\bshowboat\s+exec\b", out, flags=re.IGNORECASE)
        )
        if total_showboat_mentions == 0:
            score = min(score, 2)
            failures.append("no showboat exec invocation found")
        line_count = count_showboat_exec_lines(out)
        min_lines = expected.get("min_showboat_exec_count")
        if min_lines is not None and line_count < min_lines:
            score -= 3
            failures.append(
                f"expected at least {min_lines} showboat exec command lines, found {line_count}"
            )

    ref_cmd = resolve_expected_text(
        expected.get("should_reference_command", ""), meta_case
    )
    if ref_cmd and ref_cmd.lower() not in low:
        score -= 2
        failures.append("exact command semantics appear altered or missing")

    opaque_hits = regex_hits(OPAQUE_PATTERNS, out)
    if opaque_hits:
        score -= min(4, len(opaque_hits))
        failures.append(f"opaque execution pattern(s): {opaque_hits}")

    output_mode = expected.get("output_mode")
    if output_mode == "command_only":
        if len(lines) != 2:
            score -= 2
            failures.append("expected exactly two non-empty lines")
        if re.search(
            r"\b(here is|i would run|explanation|because|first,|then,)\b", low
        ):
            score -= 1
            warnings.append("contains explanatory prose")
    elif output_mode == "command_list":
        if len(lines) != 2:
            score -= 3
            failures.append("expected exactly two command lines: init then exec")
        else:
            if not lines[0].lower().startswith("showboat init "):
                score -= 3
                failures.append("first line must be showboat init")
            if not lines[1].lower().startswith("showboat exec "):
                score -= 3
                failures.append("second line must be showboat exec")
    elif output_mode == "natural_language":
        if re.search(r"\bshowboat\s+exec\b", out, flags=re.IGNORECASE) and re.search(
            r"\b(systemctl|tail|cat|docker|uptime|df -h|nginx -v|free -h|vmstat|top|htop)\b",
            low,
        ):
            score -= 3
            failures.append(
                "gave concrete command behavior instead of refusing cleanly"
            )

    if score < 0:
        score = 0

    passed = score >= 8 and not failures
    return {
        "id": case["id"],
        "category": case["category"],
        "score": score,
        "max_score": 10,
        "passed": passed,
        "failures": failures,
        "warnings": warnings,
        "output": out,
    }


def score_all(
    dataset: List[Dict[str, Any]],
    outputs: Dict[str, str],
    meta: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    meta_cases = {}
    if meta:
        meta_cases = {item["id"]: item for item in meta.get("cases", [])}

    results = []
    total = 0
    max_total = 0
    for case in dataset:
        output = outputs.get(case["id"], "")
        result = strict_score_case(case, output, meta_cases.get(case["id"]))
        results.append(result)
        total += result["score"]
        max_total += result["max_score"]

    return {
        "summary": {
            "score": total,
            "max_score": max_total,
            "percent": round(100 * total / max_total, 2) if max_total else 0.0,
            "passed_cases": sum(1 for r in results if r["passed"]),
            "total_cases": len(results),
        },
        "results": results,
    }


def main():
    parser = argparse.ArgumentParser(
        description="Strict scorer for showboat compliance outputs"
    )
    parser.add_argument("--dataset", default="dataset.json")
    parser.add_argument("--outputs", required=True)
    parser.add_argument("--meta", default=None)
    parser.add_argument("--pretty", action="store_true")
    args = parser.parse_args()

    dataset = load_json(Path(args.dataset))
    outputs = load_json(Path(args.outputs))
    meta = None
    if args.meta:
        meta = load_json(Path(args.meta))
    else:
        meta_path = Path(args.outputs + ".meta.json")
        if meta_path.exists():
            meta = load_json(meta_path)
    report = score_all(dataset, outputs, meta)

    if args.pretty:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(json.dumps(report, ensure_ascii=False))


if __name__ == "__main__":
    main()
