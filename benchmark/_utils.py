import json
import re
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def save_json(path: Path, data: Any) -> None:
    path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def _coerce_timeout_stream(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return str(value)


def run_command(
    cmd: List[str], timeout: int, cwd: Path
) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            cmd,
            text=True,
            capture_output=True,
            timeout=timeout,
            cwd=str(cwd),
        )
    except subprocess.TimeoutExpired as exc:
        return subprocess.CompletedProcess(
            args=exc.cmd,
            returncode=-1,
            stdout=_coerce_timeout_stream(exc.stdout),
            stderr=_coerce_timeout_stream(exc.stderr),
        )


def strip_fences(text: str) -> str:
    stripped = text.strip()
    fence_match = re.match(r"^```(?:[a-zA-Z0-9_-]+)?\n([\s\S]*?)\n```$", stripped)
    if fence_match:
        return fence_match.group(1).strip()

    embedded_match = re.search(r"```(?:json)?\n([\s\S]*?)\n```", stripped)
    if embedded_match:
        return embedded_match.group(1).strip()

    return stripped


def extract_from_json_stream(text: str) -> Optional[str]:
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


def parse_json_response(text: str) -> Optional[Dict[str, Any]]:
    extracted = extract_from_json_stream(text)
    if extracted:
        try:
            return json.loads(extracted)
        except json.JSONDecodeError:
            pass

    stripped = strip_fences(text)
    try:
        return json.loads(stripped)
    except json.JSONDecodeError:
        pass

    try:
        return json.loads(text.strip())
    except json.JSONDecodeError:
        return None
