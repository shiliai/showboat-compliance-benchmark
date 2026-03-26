#!/usr/bin/env python3
import argparse
import json
import subprocess
from pathlib import Path
from typing import Any, Dict


def load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def run(cmd, cwd: Path):
    return subprocess.run(cmd, cwd=str(cwd), text=True, capture_output=True)


def showboat(showboat_bin: str, args: list[str], cwd: Path):
    cmd = [showboat_bin] + args
    cp = run(cmd, cwd)
    if cp.returncode != 0:
        raise RuntimeError(f"showboat command failed: {' '.join(cmd)}\n{cp.stderr}")


def main():
    parser = argparse.ArgumentParser(description="Build benchmark review showboat docs")
    parser.add_argument("--outputs", required=True)
    parser.add_argument("--meta", required=True)
    parser.add_argument("--exec-report", required=True)
    parser.add_argument("--case-root", required=True)
    parser.add_argument("--artifacts-root", required=True)
    parser.add_argument("--showboat-bin", required=True)
    args = parser.parse_args()

    outputs = load_json(Path(args.outputs))
    meta = load_json(Path(args.meta))
    exec_report = load_json(Path(args.exec_report))
    exec_by_id = {item["id"]: item for item in exec_report.get("results", [])}
    meta_by_id = {item["id"]: item for item in meta.get("cases", [])}

    artifacts_root = Path(args.artifacts_root)
    artifacts_root.mkdir(parents=True, exist_ok=True)
    case_root = Path(args.case_root)

    for case_id, output in outputs.items():
        review_filename = f"benchmark-{case_id.lower()}.md"
        case_dir = Path(meta_by_id[case_id]["workspace"]).resolve()
        model_log = meta_by_id[case_id].get("log_file")
        model_log_path = (artifacts_root / model_log).resolve() if model_log else None
        agents_path = (case_dir / "AGENTS.md").resolve()
        task_path = (case_dir / "task.txt").resolve()
        exec_result = exec_by_id.get(case_id, {})

        review_file = artifacts_root / review_filename
        if review_file.exists():
            review_file.unlink()

        showboat(args.showboat_bin, ["init", review_filename, f"Benchmark review for {case_id}"], artifacts_root)
        showboat(args.showboat_bin, ["note", review_filename, f"Reviewing case {case_id} in workspace {case_dir.name}"], artifacts_root)
        showboat(args.showboat_bin, ["exec", review_filename, "bash", f"cat {agents_path}"], artifacts_root)
        showboat(args.showboat_bin, ["exec", review_filename, "bash", f"cat {task_path}"], artifacts_root)
        showboat(args.showboat_bin, ["note", review_filename, "Model output captured by benchmark:"], artifacts_root)
        escaped = output.replace("'", "'\\''")
        showboat(args.showboat_bin, ["exec", review_filename, "bash", f"printf '%s\\n' '{escaped}'"], artifacts_root)
        showboat(args.showboat_bin, ["note", review_filename, "Execution validation summary:"], artifacts_root)
        escaped_summary = json.dumps(exec_result, ensure_ascii=False).replace("'", "'\\''")
        showboat(args.showboat_bin, ["exec", review_filename, "bash", f"printf '%s\\n' '{escaped_summary}'"], artifacts_root)
        if model_log_path and model_log_path.exists():
            showboat(args.showboat_bin, ["note", review_filename, f"Generated model artifact: {model_log}"], artifacts_root)
            showboat(args.showboat_bin, ["exec", review_filename, "bash", f"cat {model_log_path}"], artifacts_root)

    print(str(artifacts_root))


if __name__ == "__main__":
    main()
