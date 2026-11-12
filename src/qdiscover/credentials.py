"""Load the selected API credential from a local .env without executing its contents."""

import os
import shlex
from pathlib import Path

API_KEY_VARIABLES = frozenset(
    {"ANTHROPIC_API_KEY", "OPENROUTER_API_KEY", "GEMINI_API_KEY", "OPENAI_API_KEY"}
)


def load_api_key(variable: str, path: Path | None = None) -> None:
    """Use the working directory's .env if the selected key is not already set.

    Accept KEY=value, optional export, single/double quotes, and # comments.
    Only the selected API key is loaded; no interpolation or shell execution occurs.
    """
    if variable not in API_KEY_VARIABLES:
        raise ValueError("Unsupported API credential variable")
    if variable in os.environ:
        return
    path = path if path is not None else Path.cwd() / ".env"
    try:
        content = path.read_text(encoding="utf-8-sig")
    except FileNotFoundError:
        return
    value = None
    for number, line in enumerate(content.splitlines(), 1):
        line = line.strip()
        if line.startswith("export ") or line.startswith("export\t"):
            line = line[6:].lstrip()
        name, separator, raw = line.partition("=")
        if not separator or name.strip() != variable:
            continue
        try:
            parts = shlex.split(raw, comments=True, posix=True)
        except ValueError:
            # Never expose a line's contents, which may contain a credential.
            raise ValueError(f"Invalid API key quoting in {path.name} at line {number}") from None
        if len(parts) > 1:
            raise ValueError(f"Quote API key values containing spaces at line {number}")
        value = parts[0] if parts else ""
    if value is not None:
        os.environ[variable] = value
