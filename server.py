"""The chat UI: a barebones Lovable in one FastAPI app.

Chat on the left, a live iframe preview on the right, and a file tree of
whatever the agent has written so far. Every `write_file` the agent makes
pushes a `files` event down the stream, which is what makes the preview
repaint mid-build instead of at the end.

The agent runs in-process — this server owns the compiled graph and streams
`astream` events straight out as SSE. No LangGraph server in the loop, so the
demo starts with one command.

One session is one directory under `workspaces/`, one thread id, and one
compiled graph. Follow-up turns hit the same checkpointer, so "make the hero
darker" edits the site that is already on disk.
"""

from __future__ import annotations

import asyncio
import json
import mimetypes
import re
import shutil
import sys
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, StreamingResponse
from langgraph.checkpoint.memory import InMemorySaver

PROJECT_DIR = Path(__file__).parent

# The agent lives in deep-agent/ so Harbor can stage just that directory —
# pointing project_path at the repo root made shutil.copytree recurse into
# its own jobs/ output.
sys.path.insert(0, str(PROJECT_DIR / "deep-agent"))

from agent import DEFAULT_MODEL, build_graph  # noqa: E402
WORKSPACES = PROJECT_DIR / "workspaces"
STATIC = PROJECT_DIR / "static"
# Every new site starts from this: a stylesheet with tokens and layout
# classes, plus a placeholder page. The agent edits rather than authoring
# 12KB of CSS, which is most of what made a cold build slow.
SCAFFOLD = PROJECT_DIR / "scaffold"

# Multi-page builds fan out to a subagent per page and then loop back through
# review and fixes, which is more steps than the default budget allows.
RECURSION_LIMIT = 150

# How the agent's tools read in the chat transcript. Anything not listed here
# still shows up, just under its raw tool name.
TOOL_LABELS = {
    "write_file": "Writing",
    "edit_file": "Editing",
    "read_file": "Reading",
    "delete": "Deleting",
    "ls": "Listing files",
    "glob": "Searching files",
    "grep": "Searching contents",
    "execute": "Running",
    "check_site": "Checking the site",
    "task": "Delegating",
    "write_todos": "Planning",
}


@dataclass
class Session:
    id: str
    dir: Path
    graph: Any
    model: str
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)


SESSIONS: dict[str, Session] = {}

app = FastAPI(title="website-builder-demo")


def _new_session(model: str | None = None) -> Session:
    sid = uuid.uuid4().hex[:12]
    site_dir = WORKSPACES / sid
    site_dir.mkdir(parents=True, exist_ok=True)
    if SCAFFOLD.is_dir():
        for source in SCAFFOLD.iterdir():
            if source.is_file():
                shutil.copy2(source, site_dir / source.name)
    session = Session(
        id=sid,
        dir=site_dir,
        # A checkpointer per session, so follow-up turns see the conversation
        # and the agent edits the site instead of rebuilding it.
        graph=build_graph(site_dir=site_dir, model=model, checkpointer=InMemorySaver()),
        model=model or DEFAULT_MODEL,
    )
    SESSIONS[sid] = session
    return session


def _get_session(sid: str) -> Session:
    session = SESSIONS.get(sid)
    if session is None:
        raise HTTPException(status_code=404, detail="unknown session — reload the page")
    return session


def _file_tree(site_dir: Path) -> list[dict]:
    """Everything the agent has written, newest-relevant first."""
    files = []
    for path in sorted(site_dir.rglob("*")):
        if path.is_dir() or path.name.startswith("."):
            continue
        files.append({
            "path": path.relative_to(site_dir).as_posix(),
            "size": path.stat().st_size,
        })
    # index.html first — it is what the preview opens.
    files.sort(key=lambda f: (f["path"] != "index.html", f["path"]))
    return files


def _sse(event: dict) -> str:
    return f"data: {json.dumps(event)}\n\n"


def _normalize(chunk: Any) -> tuple[tuple, str | None, Any]:
    """Flatten one astream chunk into (namespace, mode, payload).

    With `subgraphs=True` and several stream modes, LangGraph yields
    3-tuples; either option alone yields a 2-tuple. Normalizing here keeps
    the event loop below readable.
    """
    if isinstance(chunk, tuple):
        if len(chunk) == 3:
            return chunk
        if len(chunk) == 2:
            first, second = chunk
            if isinstance(first, tuple):
                return first, None, second
            return (), first, second
    return (), None, chunk


def _text_of(content: Any) -> str:
    """Message content as plain text, whatever block shape it arrived in."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(
            block.get("text", "")
            for block in content
            if isinstance(block, dict) and block.get("type") == "text"
        )
    return ""


def _describe_tool(name: str, args: dict) -> dict:
    """Turn a tool call into the one line the chat pane shows."""
    label = TOOL_LABELS.get(name, name)
    detail = ""
    if name in {"write_file", "edit_file", "read_file", "delete"}:
        detail = str(args.get("file_path") or args.get("path") or "")
    elif name == "task":
        detail = str(args.get("subagent_type") or "")
    elif name in {"glob", "grep"}:
        detail = str(args.get("pattern") or "")
    elif name == "execute":
        detail = str(args.get("command") or "")[:80]
    return {"type": "tool", "name": name, "label": label, "detail": detail}


# Tool names whose start we do not announce: the todo list renders as its own
# card, so a "Planning" row above it is just noise.
_QUIET_ON_START = {"write_todos"}

_PATH_IN_PARTIAL_ARGS = re.compile(r'"(?:file_path|path)"\s*:\s*"([^"]*)"')
_SUBAGENT_IN_PARTIAL_ARGS = re.compile(r'"subagent_type"\s*:\s*"([^"]*)"')


def _announce_tool_starts(
    chunks: list, pending: dict[int, dict], announced: set[str], namespace: tuple
) -> list[dict]:
    """Turn streaming tool-argument chunks into chat rows.

    Yields one event when a call's name first appears, and another once its
    path can be parsed out of the partial argument JSON.
    """
    events: list[dict] = []
    agent = namespace[-1].split(":")[0] if namespace else "builder"

    for chunk in chunks:
        index = chunk.get("index") or 0
        name = chunk.get("name")

        if name:
            # A name means a new call at this index.
            call_id = chunk.get("id") or f"call-{len(announced)}-{index}"
            pending[index] = {"id": call_id, "name": name, "args": "", "detailed": False}
            if name not in _QUIET_ON_START:
                announced.add(call_id)
                events.append({
                    "type": "tool",
                    "id": call_id,
                    "name": name,
                    "label": TOOL_LABELS.get(name, name),
                    "detail": "",
                    "agent": agent,
                })

        entry = pending.get(index)
        if entry is None or entry["detailed"]:
            continue

        entry["args"] += chunk.get("args") or ""
        pattern = (
            _SUBAGENT_IN_PARTIAL_ARGS if entry["name"] == "task" else _PATH_IN_PARTIAL_ARGS
        )
        match = pattern.search(entry["args"])
        if match and match.group(1):
            entry["detailed"] = True
            if entry["id"] in announced:
                events.append({
                    "type": "tool_detail",
                    "id": entry["id"],
                    "detail": match.group(1),
                })

    return events


async def _run_turn(session: Session, message: str):
    """Stream one turn of the agent as SSE events."""
    config = {
        "configurable": {
            "thread_id": session.id,
            "cwd": str(session.dir),
            "model": session.model,
        },
        "recursion_limit": RECURSION_LIMIT,
    }

    # `files` events are what repaint the preview. Only send one when the set
    # of files or their sizes actually changed, so the iframe is not thrashing
    # on every read_file.
    last_tree: list[dict] = []
    # index -> {id, name, args}; ids we have already put on screen
    pending: dict[int, dict] = {}
    announced: set[str] = set()

    def tree_event() -> dict | None:
        nonlocal last_tree
        tree = _file_tree(session.dir)
        if tree != last_tree:
            last_tree = tree
            return {"type": "files", "files": tree}
        return None

    yield _sse({"type": "start", "session_id": session.id})

    try:
        async for chunk in session.graph.astream(
            {"messages": [{"role": "user", "content": message}]},
            config,
            stream_mode=["updates", "messages"],
            subgraphs=True,
        ):
            namespace, mode, payload = _normalize(chunk)
            in_subagent = bool(namespace)

            if mode == "messages":
                msg_chunk, metadata = payload
                if getattr(msg_chunk, "type", "") != "AIMessageChunk":
                    continue

                # Tool arguments stream in before the call is complete. Waiting
                # for the `updates` event means ~a minute of dead air while a
                # large write_file streams, which reads as a hang. Announce the
                # call as soon as its name arrives, then fill in the path once
                # enough of the argument JSON has landed to parse it out.
                for event in _announce_tool_starts(
                    getattr(msg_chunk, "tool_call_chunks", None) or [],
                    pending,
                    announced,
                    namespace,
                ):
                    yield _sse(event)

                text = _text_of(getattr(msg_chunk, "content", ""))
                if not text:
                    continue
                # Subagent narration is interesting but it drowns the chat.
                # It is streamed on a separate channel the UI dims.
                yield _sse({
                    "type": "subagent_text" if in_subagent else "text",
                    "text": text,
                    "agent": namespace[-1].split(":")[0] if in_subagent else "builder",
                })
                continue

            if mode != "updates" or not isinstance(payload, dict):
                continue

            for update in payload.values():
                if not isinstance(update, dict):
                    continue
                for msg in update.get("messages") or []:
                    for call in getattr(msg, "tool_calls", None) or []:
                        args = call.get("args") or {}
                        if call.get("name") == "write_todos":
                            yield _sse({"type": "todos", "todos": args.get("todos") or []})
                            continue
                        event = _describe_tool(call.get("name", "?"), args)
                        event["agent"] = namespace[-1].split(":")[0] if in_subagent else "builder"
                        call_id = call.get("id")
                        if call_id in announced:
                            # Already on screen — just complete its detail.
                            yield _sse({
                                "type": "tool_detail",
                                "id": call_id,
                                "detail": event["detail"],
                            })
                        else:
                            event["id"] = call_id
                            yield _sse(event)

                    if getattr(msg, "type", "") == "tool":
                        name = getattr(msg, "name", "")
                        if name in {"task", "check_site"}:
                            yield _sse({
                                "type": "tool_result",
                                "name": name,
                                "text": _text_of(getattr(msg, "content", ""))[:2000],
                            })
                        if name in {"write_file", "edit_file", "delete"}:
                            if event := tree_event():
                                yield _sse(event)

    except Exception as exc:  # surface it in the UI rather than a dead stream
        yield _sse({"type": "error", "message": f"{type(exc).__name__}: {exc}"})

    if event := tree_event():
        yield _sse(event)
    yield _sse({"type": "done"})


@app.get("/", response_class=HTMLResponse)
async def index() -> HTMLResponse:
    return HTMLResponse((STATIC / "index.html").read_text(encoding="utf-8"))


@app.post("/api/session")
async def create_session(request: Request) -> JSONResponse:
    body = {}
    try:
        body = await request.json()
    except Exception:
        pass
    session = _new_session(model=body.get("model"))
    return JSONResponse({
        "session_id": session.id,
        "model": session.model,
        "files": _file_tree(session.dir),
    })


@app.post("/api/chat")
async def chat(request: Request) -> StreamingResponse:
    body = await request.json()
    message = (body.get("message") or "").strip()
    if not message:
        raise HTTPException(status_code=400, detail="empty message")
    session = _get_session(body.get("session_id") or "")

    if session.lock.locked():
        raise HTTPException(status_code=409, detail="this session is already building")

    async def stream():
        async with session.lock:
            async for event in _run_turn(session, message):
                yield event

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.get("/api/files")
async def files(session_id: str) -> JSONResponse:
    return JSONResponse({"files": _file_tree(_get_session(session_id).dir)})


@app.get("/api/file")
async def file_contents(session_id: str, path: str) -> JSONResponse:
    session = _get_session(session_id)
    target = (session.dir / path).resolve()
    if not target.is_file() or session.dir.resolve() not in target.parents:
        raise HTTPException(status_code=404, detail="no such file")
    return JSONResponse({"path": path, "content": target.read_text(encoding="utf-8", errors="replace")})


@app.get("/preview/{session_id}/{path:path}")
async def preview(session_id: str, path: str) -> FileResponse:
    """Serve the generated site so the iframe can render it."""
    session = _get_session(session_id)
    target = (session.dir / (path or "index.html")).resolve()
    if target.is_dir():
        target = target / "index.html"
    # Confine serving to the session's own workspace.
    if not target.is_file() or session.dir.resolve() not in target.parents:
        raise HTTPException(status_code=404, detail="not built yet")
    media_type, _ = mimetypes.guess_type(target.name)
    return FileResponse(
        target,
        media_type=media_type or "application/octet-stream",
        headers={"Cache-Control": "no-store"},
    )
