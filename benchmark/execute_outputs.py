#!/usr/bin/env python3
import argparse
import json
import shlex
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional


def load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def save_json(path: Path, data: Any):
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def extract_output_blocks(markdown: str) -> int:
    return markdown.count("```output")


def normalize_lines(command_text: str) -> List[str]:
    lines = []
    for line in command_text.splitlines():
        line = line.strip()
        if not line:
            continue
        lines.append(line)
    return lines


def execute_case(case_id: str, command_text: str, workdir: Path, timeout: int, showboat_bin: Optional[str] = None) -> Dict[str, Any]:
    result: Dict[str, Any] = {
        "id": case_id,
        "command": command_text.strip(),
        "executed": False,
        "safe": False,
    }

    lines = normalize_lines(command_text)
    if not lines:
        result["error"] = "empty output"
        return result
    if len(lines) > 2:
        result["error"] = "expected at most two command lines"
        return result

    parsed = []
    log_file = None
    saw_exec = False

    for line in lines:
        if not (line.lower().startswith("showboat init ") or line.lower().startswith("showboat exec ")):
            result["error"] = "all lines must start with showboat init/exec"
            return result
        parts = shlex.split(line)
        if len(parts) < 3:
            result["error"] = "command too short"
            return result
        if showboat_bin:
            parts[0] = showboat_bin
        kind = parts[1]
        if kind == "init":
            if len(parts) < 4:
                result["error"] = "showboat init requires file and title"
                return result
            current_log = parts[2]
        elif kind == "exec":
            if len(parts) < 5:
                result["error"] = "showboat exec requires file, lang, and code"
                return result
            current_log = parts[2]
            if parts[3] != "bash":
                result["error"] = f"expected bash language, got {parts[3]}"
                return result
            saw_exec = True
        else:
            result["error"] = "unsupported showboat subcommand"
            return result

        if log_file is None:
            log_file = current_log
        elif log_file != current_log:
            result["error"] = "all commands must use the same log file"
            return result
        parsed.append(parts)

    if not saw_exec:
        result["error"] = "missing showboat exec command"
        return result

    result["safe"] = True
    result["log_file"] = log_file
    log_path = workdir / log_file
    if log_path.exists():
        log_path.unlink()

    result["steps"] = []
    for parts in parsed:
        try:
            cp = subprocess.run(parts, cwd=str(workdir), text=True, capture_output=True, timeout=timeout)
            result["steps"].append({
                "argv": parts,
                "returncode": cp.returncode,
                "stdout": cp.stdout[-4000:],
                "stderr": cp.stderr[-4000:],
            })
            result["executed"] = True
            if cp.returncode != 0:
                result["returncode"] = cp.returncode
                result["stderr"] = cp.stderr[-4000:]
                result["stdout"] = cp.stdout[-4000:]
                break
        except subprocess.TimeoutExpired:
            result["executed"] = True
            result["timeout"] = True
            return result

    result["log_exists"] = log_path.exists()
    if log_path.exists():
        markdown = log_path.read_text(encoding="utf-8", errors="replace")
        result["log_size"] = log_path.stat().st_size
        result["output_blocks"] = extract_output_blocks(markdown)
        result["has_bash_block"] = "```bash" in markdown
        result["has_output_block"] = "```output" in markdown
    return result


def main():
    parser = argparse.ArgumentParser(description="Execute model-emitted showboat commands and verify markdown artifacts")
    parser.add_argument("--outputs", required=True)
    parser.add_argument("--workdir", default="artifacts")
    parser.add_argument("--timeout", type=int, default=60)
    parser.add_argument("--showboat-bin", default=None)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    outputs = load_json(Path(args.outputs))
    workdir = Path(args.workdir)
    workdir.mkdir(parents=True, exist_ok=True)

    results: List[Dict[str, Any]] = []
    for case_id, command_text in outputs.items():
        results.append(execute_case(case_id, command_text, workdir, args.timeout, args.showboat_bin))

    summary = {
        "total_cases": len(results),
        "safe_cases": sum(1 for r in results if r.get("safe")),
        "executed_cases": sum(1 for r in results if r.get("executed")),
        "artifact_cases": sum(1 for r in results if r.get("log_exists")),
        "output_block_cases": sum(1 for r in results if r.get("has_output_block")),
    }

    save_json(Path(args.output), {"summary": summary, "results": results})
    print(args.output)


if __name__ == "__main__":
    main()
