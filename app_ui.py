from __future__ import annotations

import os
from threading import Lock
from typing import Any

from flask import Flask, jsonify, render_template, request

import main as assistant

app = Flask(__name__)
assistant_lock = Lock()
ENV_FILE = ".env"


def _history() -> list[dict[str, Any]]:
    return assistant.read_json_list(assistant.chat_history_file)


def _settings_payload() -> dict[str, Any]:
    return {
        "model": os.getenv("OPENROUTER_MODEL", "openai/gpt-5.2"),
        "max_tokens": int(os.getenv("OPENROUTER_MAX_TOKENS", "512")),
        "site_url": os.getenv("OPENROUTER_SITE_URL", ""),
        "site_name": os.getenv("OPENROUTER_SITE_NAME", ""),
    }


def _persist_env_values(values: dict[str, str]) -> None:
    existing_lines: list[str] = []
    if os.path.exists(ENV_FILE):
        with open(ENV_FILE, "r", encoding="utf-8") as file:
            existing_lines = file.read().splitlines()

    for key, value in values.items():
        os.environ[key] = value

    updated_lines: list[str] = []
    handled_keys = set(values.keys())

    for line in existing_lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in line:
            updated_lines.append(line)
            continue

        key, _ = line.split("=", 1)
        key = key.strip()
        if key in values:
            updated_lines.append(f"{key}={values[key]}")
            handled_keys.discard(key)
        else:
            updated_lines.append(line)

    for key in handled_keys:
        updated_lines.append(f"{key}={values[key]}")

    with open(ENV_FILE, "w", encoding="utf-8") as file:
        file.write("\n".join(updated_lines).strip() + "\n")


def _message_signature(item: dict[str, Any]) -> tuple[str, str, str]:
    return (
        str(item.get("time", "")),
        str(item.get("role", "")),
        str(item.get("text", "")),
    )


def _assistant_messages_after(before_history: list[dict[str, Any]]) -> list[str]:
    before_signatures = {_message_signature(item) for item in before_history}
    after_history = _history()
    messages: list[str] = []

    for item in after_history:
        signature = _message_signature(item)
        if signature in before_signatures:
            continue
        if item.get("role") == "assistant" and item.get("text"):
            messages.append(str(item.get("text")))

    return messages


@app.get("/")
def index() -> str:
    return render_template("index.html")


@app.get("/api/history")
def api_history():
    limit = request.args.get("limit", default=20, type=int)
    limit = max(1, min(limit, 100))
    history = _history()[-limit:]
    return jsonify({"history": history})


@app.get("/api/settings")
def api_settings_get():
    return jsonify({"settings": _settings_payload()})


@app.post("/api/settings")
def api_settings_save():
    payload = request.get_json(silent=True) or {}

    model = str(payload.get("model", "")).strip() or "openai/gpt-5.2"
    max_tokens = payload.get("max_tokens", 512)
    site_url = str(payload.get("site_url", "")).strip()
    site_name = str(payload.get("site_name", "")).strip()

    try:
        max_tokens_int = int(max_tokens)
    except (ValueError, TypeError):
        return jsonify({"error": "max_tokens must be a number."}), 400

    max_tokens_int = max(64, min(max_tokens_int, 4096))

    _persist_env_values(
        {
            "OPENROUTER_MODEL": model,
            "OPENROUTER_MAX_TOKENS": str(max_tokens_int),
            "OPENROUTER_SITE_URL": site_url,
            "OPENROUTER_SITE_NAME": site_name,
        }
    )

    return jsonify({"settings": _settings_payload(), "saved": True})


@app.post("/api/command")
def api_command():
    payload = request.get_json(silent=True) or {}
    command = str(payload.get("command", "")).strip()
    voice_output = bool(payload.get("voice_output", False))

    if not command:
        return jsonify({"error": "Command is required."}), 400

    with assistant_lock:
        assistant.set_voice_output(voice_output)
        before_history = _history()

        try:
            assistant.processCommand(command)
        except SystemExit:
            # Keep API stable even if user command asks assistant to stop.
            pass

        messages = _assistant_messages_after(before_history)

    if not messages:
        messages = ["I processed your command, but no response was produced."]

    return jsonify({"messages": messages})


@app.post("/api/listen")
def api_listen():
    payload = request.get_json(silent=True) or {}
    voice_output = bool(payload.get("voice_output", False))

    with assistant_lock:
        assistant.set_voice_output(voice_output)
        before_history = _history()

        try:
            transcript = assistant.listen_once(timeout=6, phrase_time_limit=7)
            assistant.processCommand(transcript)
        except Exception as e:
            return jsonify({"error": f"Microphone listen failed: {e}"}), 400

        messages = _assistant_messages_after(before_history)

    if not messages:
        messages = ["I heard you, but no response was produced."]

    return jsonify({"transcript": transcript, "messages": messages})


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=True)
