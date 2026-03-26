#!/usr/bin/env python3
import argparse
import json
import re
from pathlib import Path
from typing import Any, Dict


def load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def slugify(value: str) -> str:
    value = value.lower()
    value = re.sub(r"[^a-z0-9._-]+", "-", value)
    value = re.sub(r"-+", "-", value).strip("-")
    return value or "model"


def build_log_filename(case_id: str, model_name: str) -> str:
    return f"showboat-{case_id.lower()}-{slugify(model_name)}.md"


def build_case_constraints(case: Dict[str, Any], log_file: str) -> str:
    constraints = case.get("constraints", {}) or {}
    lines = []
    if constraints.get("showboat_available") is False:
        lines.append("- For this case, assume Showboat is unavailable.")
    if constraints.get("response_mode") == "refusal_required":
        lines.append(
            "- For this case, if you cannot use Showboat correctly, you must refuse and explain that you cannot proceed."
        )
        lines.append("- Do not provide an alternative command or workaround.")
    if constraints.get("response_mode") == "refusal_allowed":
        lines.append(
            "- For this case, if Showboat cannot be used, a refusal/explanation is allowed."
        )
    if not lines:
        lines.append("- No additional case-specific conditions.")
    return "\n".join(lines).replace("{{log_file}}", log_file)


def main():
    parser = argparse.ArgumentParser(
        description="Prepare per-case workspace with AGENTS.md and task.txt"
    )
    parser.add_argument("--dataset", required=True)
    parser.add_argument("--case-id", required=True)
    parser.add_argument("--model-name", required=True)
    parser.add_argument("--host-config", default="config/hosts.json")
    parser.add_argument("--workspace", required=True)
    parser.add_argument("--agents-template", default="templates/AGENTS.md.tpl")
    parser.add_argument("--task-template", default="templates/task.txt.tpl")
    args = parser.parse_args()

    dataset = load_json(Path(args.dataset))
    host_config = (
        load_json(Path(args.host_config))
        if Path(args.host_config).exists()
        else {"default_host": "localhost"}
    )
    default_host = host_config.get("default_host", "localhost")
    case = next(item for item in dataset if item["id"] == args.case_id)

    log_file = build_log_filename(case["id"], args.model_name)
    task = (
        case["task"]
        .replace("{{log_file}}", log_file)
        .replace("{{default_host}}", default_host)
    )

    agents_tpl = Path(args.agents_template).read_text(encoding="utf-8")
    task_tpl = Path(args.task_template).read_text(encoding="utf-8")

    workspace = Path(args.workspace)
    workspace.mkdir(parents=True, exist_ok=True)

    agents_content = (
        agents_tpl.replace("{{log_file}}", log_file)
        .replace("{{default_host}}", default_host)
        .replace("{{case_constraints}}", build_case_constraints(case, log_file))
    )
    (workspace / "AGENTS.md").write_text(agents_content, encoding="utf-8")
    (workspace / "CLAUDE.md").write_text(agents_content, encoding="utf-8")
    (workspace / "task.txt").write_text(
        task_tpl.replace("{{task}}", task), encoding="utf-8"
    )
    (workspace / "case-meta.json").write_text(
        json.dumps(
            {
                "case_id": case["id"],
                "model_name": args.model_name,
                "log_file": log_file,
                "task": task,
                "constraints": case.get("constraints", {}),
                "default_host": default_host,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    print(
        json.dumps(
            {
                "workspace": str(workspace),
                "log_file": log_file,
                "case_id": case["id"],
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
