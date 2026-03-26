#!/usr/bin/env python3
import argparse
import json
import re
import shlex
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict


def load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def save_json(path: Path, data: Any):
    path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def run_command(cmd, timeout: int, cwd: Path) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(
            cmd, text=True, capture_output=True, timeout=timeout, cwd=str(cwd)
        )
    except subprocess.TimeoutExpired as e:
        # Return a CompletedProcess-like object indicating timeout
        return subprocess.CompletedProcess(
            args=e.cmd,
            returncode=-1,
            stdout=e.stdout.decode("utf-8") if e.stdout else "",
            stderr=e.stderr.decode("utf-8") if e.stderr else "",
        )


def strip_fences(text: str) -> str:
    stripped = text.strip()
    fence_match = re.match(r"^```(?:[a-zA-Z0-9_-]+)?\n([\s\S]*?)\n```$", stripped)
    if fence_match:
        return fence_match.group(1).strip()
    return stripped


def extract_from_json_stream(text: str):
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
    text = stdout.strip()
    if text:
        extracted = extract_from_json_stream(text)
        if extracted:
            return extracted
        return strip_fences(text)
    if stderr.strip():
        return stderr.strip()
    return f"<empty output, returncode={returncode}>"


def main():
    parser = argparse.ArgumentParser(
        description="Run showboat benchmark inside per-case workspaces with AGENTS.md/task.txt"
    )
    parser.add_argument(
        "--runner",
        required=True,
        help="Runner command prefix. Prompt/task text is appended as final argv item.",
    )
    parser.add_argument("--model-name", required=True)
    parser.add_argument("--timeout", type=int, default=300)
    parser.add_argument("--output", default="outputs.json")
    parser.add_argument("--print-live", action="store_true")
    parser.add_argument("--case-root", default="case-workspaces")
    args = parser.parse_args()

    case_root = Path(args.case_root)
    outputs: Dict[str, str] = {}
    meta: Dict[str, Any] = {
        "runner": args.runner,
        "model_name": args.model_name,
        "timeout": args.timeout,
        "cases": [],
    }

    for case_dir in sorted([p for p in case_root.iterdir() if p.is_dir()]):
        meta_path = case_dir / "case-meta.json"
        task_path = case_dir / "task.txt"
        if not meta_path.exists() or not task_path.exists():
            continue
        case_meta = load_json(meta_path)
        case_id = case_meta["case_id"]
        task = task_path.read_text(encoding="utf-8")

        cmd = shlex.split(args.runner)
        cmd.append(task)

        if args.print_live:
            print(f"=== {case_id} ===", file=sys.stderr)
            print(f"workspace: {case_dir}", file=sys.stderr)
            print(f"log file: {case_meta.get('log_file')}", file=sys.stderr)
            print("--- task start ---", file=sys.stderr)
            print(task, file=sys.stderr)
            print("--- task end ---", file=sys.stderr)
            print("$ " + " ".join(shlex.quote(x) for x in cmd), file=sys.stderr)

        cp = run_command(cmd, timeout=args.timeout, cwd=case_dir)

        # Handle timeout gracefully
        if cp.returncode == -1:
            print(
                f"WARNING: {case_id} timed out after {args.timeout} seconds",
                file=sys.stderr,
            )
            output = f"<timeout after {args.timeout} seconds>"
        else:
            output = default_adapter(cp.stdout, cp.stderr, cp.returncode)

        outputs[case_id] = output
        meta["cases"].append(
            {
                "id": case_id,
                "workspace": str(case_dir),
                "log_file": case_meta.get("log_file"),
                "returncode": cp.returncode,
                "stdout_len": len(cp.stdout),
                "stderr_len": len(cp.stderr),
            }
        )
        if args.print_live:
            print(output[:2000], file=sys.stderr)
            print(file=sys.stderr)

    out_path = Path(args.output)
    save_json(out_path, outputs)
    save_json(out_path.with_suffix(out_path.suffix + ".meta.json"), meta)
    print(str(out_path))


if __name__ == "__main__":
    main()
