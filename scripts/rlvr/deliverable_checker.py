"""Issue checker receipts from the orchestrator's Agent completion hook."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from _common import atomic_write_text
from rlvr import learning_seal

_REQUEST = "deliverable-use-review/1"
_RECORD = "deliverable-use/1"
_FIELDS = ("schema", "fact_id", "deliverable", "fact_sha256",
           "deliverable_sha256", "excerpt", "verdict", "reason")


def _object(text: str) -> dict:
    try:
        value = json.loads(text)
    except ValueError:
        return {}
    return value if isinstance(value, dict) else {}


def _workspace_key(root: Path) -> str:
    return hashlib.sha256(str(root.resolve()).encode()).hexdigest()


def _review_assignment(payload: dict) -> dict:
    if (payload.get("hook_event_name") != "PostToolUse"
            or payload.get("tool_name") != "Agent"
            or payload.get("agent_id")):
        return {}
    tool_input = payload.get("tool_input")
    if not isinstance(tool_input, dict) or tool_input.get("subagent_type") != "general-purpose":
        return {}
    name = tool_input.get("name")
    if not isinstance(name, str) or not name.startswith("deliverable-use-"):
        return {}
    if tool_input.get("run_in_background") is not False or any(
            key in tool_input for key in ("resume", "agent_id", "agentId")):
        return {}
    prompt = tool_input.get("prompt")
    if not isinstance(prompt, str):
        return {}
    assignment = _object(prompt.partition("\n")[0])
    return assignment if assignment.get("schema") == _REQUEST else {}


def _checker_return(payload: dict, assignment: dict) -> tuple[dict, str] | None:
    response = payload.get("tool_response")
    if not isinstance(response, dict) or response.get("status") != "completed":
        return None
    checker = response.get("agentId")
    content = response.get("content")
    if not isinstance(checker, str) or not checker.strip() or not isinstance(content, list):
        return None
    if len(content) != 1 or not isinstance(content[0], dict):
        return None
    text = content[0].get("text")
    if content[0].get("type") != "text" or not isinstance(text, str):
        return None
    record = _object(text)
    if (record.get("schema") != _RECORD or record.get("verdict") != "used"
            or not all(isinstance(record.get(key), str) and record[key].strip()
                       for key in _FIELDS)):
        return None
    if any(record[key] != assignment.get(key) for key in ("fact_id", "deliverable")):
        return None
    return {key: record[key] for key in _FIELDS}, checker


def capture(ws: str | Path, payload: dict) -> bool:
    """Persist one sealed result for an orchestrator-initiated review call."""
    assignment = _review_assignment(payload)
    if not assignment or not learning_seal.armed():
        return False
    result = _checker_return(payload, assignment)
    session = payload.get("session_id")
    call = payload.get("tool_use_id")
    if result is None or not all(isinstance(value, str) and value.strip()
                                 for value in (session, call)):
        return False
    record, checker = result
    root = Path(ws).resolve()
    directory = root / "runs" / "deliverable-use"
    if directory.resolve() != directory:
        return False
    identity = {"workspace": _workspace_key(root), "session_id": session,
                "tool_use_id": call, "kind": _REQUEST}
    envelope = learning_seal.sign_row(
        {**record, "verifier_id": checker, "checker_host": identity})
    if "seal" not in envelope:
        return False
    event_id = hashlib.sha256(json.dumps([session, call]).encode()).hexdigest()
    artifact = directory / f"host-{event_id}.json"
    if not artifact.exists():
        atomic_write_text(artifact, json.dumps(envelope, sort_keys=True) + "\n", unique=True)
    return True


def is_host_bound(root: Path, record: dict) -> bool:
    host = record.get("checker_host")
    return (isinstance(host, dict) and host.get("kind") == _REQUEST
            and host.get("workspace") == _workspace_key(root)
            and learning_seal.verify_row(record)[0])
