"""Generate the Markdown settings reference for MkDocs."""
from __future__ import annotations

import inspect
import textwrap
from pathlib import Path
from typing import List

import re

import gunicorn.config as guncfg

HEAD = """\
> **Generated file** — update `gunicorn/config.py` instead.

# Settings

This reference is built directly from `gunicorn.config.KNOWN_SETTINGS` and is
regenerated during every documentation build.

!!! note
    Settings can be provided through the `GUNICORN_CMD_ARGS` environment
    variable. For example:

    ```console
    $ GUNICORN_CMD_ARGS="--bind=127.0.0.1 --workers=3" gunicorn app:app
    ```

    _Added in 19.7._

"""


def _format_default(setting: guncfg.Setting) -> tuple[str, bool]:
    if hasattr(setting, "default_doc"):
        text = textwrap.dedent(setting.default_doc).strip("\n")
        return text, True
    default = setting.default
    if callable(default):
        source = textwrap.dedent(inspect.getsource(default)).strip("\n")
        return f"```python\n{source}\n```", True
    if default == "":
        return "`''`", False
    return f"`{default!r}`", False


def _format_cli(setting: guncfg.Setting) -> str | None:
    if not setting.cli:
        return None
    if setting.meta:
        variants = [f"`{opt} {setting.meta}`" for opt in setting.cli]
    else:
        variants = [f"`{opt}`" for opt in setting.cli]
    return ", ".join(variants)


REF_MAP = {
    "forwarded-allow-ips": ("reference/settings.md", "forwarded_allow_ips"),
    "forwarder-headers": ("reference/settings.md", "forwarder_headers"),
    "proxy-allow-ips": ("reference/settings.md", "proxy_allow_ips"),
    "worker-class": ("reference/settings.md", "worker_class"),
    "reload": ("reference/settings.md", "reload"),
    "raw-env": ("reference/settings.md", "raw_env"),
    "check-config": ("reference/settings.md", "check_config"),
    "errorlog": ("reference/settings.md", "errorlog"),
    "logconfig": ("reference/settings.md", "logconfig"),
    "logconfig-json": ("reference/settings.md", "logconfig_json"),
    "ssl-context": ("reference/settings.md", "ssl_context"),
    "ssl-version": ("reference/settings.md", "ssl_version"),
    "blocking-os-fchmod": ("reference/settings.md", "blocking_os_fchmod"),
    "configuration_file": ("../configure.md", "configuration-file"),
}

REF_PATTERN = re.compile(r":ref:`([^`]+)`")


def _convert_refs(text: str) -> str:
    def repl(match: re.Match[str]) -> str:
        raw = match.group(1)
        if "<" in raw and raw.endswith(">"):
            label, target = raw.split("<", 1)
            target = target[:-1]
            label = label.replace("\n", " ").strip()
        else:
            label, target = None, raw.strip()
        info = REF_MAP.get(target)
        if not info:
            return (label or target).replace("\n", " ").strip()
        path, anchor = info
        if path.endswith(".md"):
            if path == "reference/settings.md" and anchor:
                href = f"#{anchor}"
            else:
                href = path + (f"#{anchor}" if anchor else "")
        else:
            href = path + (f"#{anchor}" if anchor else "")
        text = (label or target).replace("\n", " ").strip()
        return f"[{text}]({href})"

    return REF_PATTERN.sub(repl, text)


def _consume_indented(lines: List[str], start: int) -> tuple[str, int]:
    body: List[str] = []
    i = start
    while i < len(lines):
        line = lines[i]
        if line.startswith("   ") or not line.strip():
            body.append(line)
            i += 1
        else:
            break
    text = textwrap.dedent("\n".join(body)).strip("\n")
    return text, i


def _convert_desc(desc: str) -> str:
    raw_lines = textwrap.dedent(desc).splitlines()
    output: List[str] = []
    i = 0
    while i < len(raw_lines):
        line = raw_lines[i]
        stripped = line.strip()
        if stripped.startswith(".. note::"):
            body, i = _consume_indented(raw_lines, i + 1)
            output.append("!!! note")
            if body:
                for body_line in body.splitlines():
                    output.append(f"    {body_line}" if body_line else "")
            output.append("")
            continue
        if stripped.startswith(".. warning::"):
            body, i = _consume_indented(raw_lines, i + 1)
            output.append("!!! warning")
            if body:
                for body_line in body.splitlines():
                    output.append(f"    {body_line}" if body_line else "")
            output.append("")
            continue
        if stripped.startswith(".. deprecated::"):
            version = stripped.split("::", 1)[1].strip()
            body, i = _consume_indented(raw_lines, i + 1)
            title = f"Deprecated in {version}" if version else "Deprecated"
            output.append(f"!!! danger \"{title}\"")
            if body:
                for body_line in body.splitlines():
                    output.append(f"    {body_line}" if body_line else "")
            output.append("")
            continue
        if stripped.startswith(".. versionadded::"):
            version = stripped.split("::", 1)[1].strip()
            body, i = _consume_indented(raw_lines, i + 1)
            title = f"Added in {version}" if version else "Added"
            output.append(f"!!! info \"{title}\"")
            if body:
                for body_line in body.splitlines():
                    output.append(f"    {body_line}" if body_line else "")
            output.append("")
            continue
        if stripped.startswith(".. versionchanged::"):
            version = stripped.split("::", 1)[1].strip()
            body, i = _consume_indented(raw_lines, i + 1)
            title = f"Changed in {version}" if version else "Changed"
            output.append(f"!!! info \"{title}\"")
            if body:
                for body_line in body.splitlines():
                    output.append(f"    {body_line}" if body_line else "")
            output.append("")
            continue
        if stripped.startswith(".. code::") or stripped.startswith(".. code-block::"):
            language = stripped.split("::", 1)[1].strip()
            body, i = _consume_indented(raw_lines, i + 1)
            fence = language or "text"
            output.append(f"```{fence}")
            if body:
                output.append(body)
            output.append("```")
            output.append("")
            continue

        output.append(line)
        i += 1

    text = "\n".join(output)
    text = _convert_refs(text)
    # Collapse excessive blank lines
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip("\n")


def _format_setting(setting: guncfg.Setting) -> str:
    lines: list[str] = [f"## `{setting.name}`", ""]

    cli = _format_cli(setting)
    if cli:
        lines.extend((f"**Command line:** {cli}", ""))

    default_text, is_block = _format_default(setting)
    if is_block:
        lines.append("**Default:**")
        lines.append("")
        lines.append(default_text)
    else:
        lines.append(f"**Default:** {default_text}")
    lines.append("")

    desc = _convert_desc(setting.desc)
    if desc:
        lines.append(desc)
        lines.append("")

    return "\n".join(lines)


def render_settings() -> str:
    sections: list[str] = [HEAD, '<span id="blocking_os_fchmod"></span>', ""]
    known_settings = sorted(guncfg.KNOWN_SETTINGS, key=lambda s: s.section)
    current_section: str | None = None

    for setting in known_settings:
        if setting.section != current_section:
            current_section = setting.section
            sections.append(f"# {current_section}\n")
        sections.append(_format_setting(setting))

    return "\n".join(sections).strip() + "\n"


def _write_output(markdown: str) -> None:
    try:
        import mkdocs_gen_files  # type: ignore
    except ImportError:
        mkdocs_gen_files = None

    if mkdocs_gen_files is not None:
        try:
            with mkdocs_gen_files.open("reference/settings.md", "w") as fh:
                fh.write(markdown)
                return
        except Exception:
            pass

    output = Path(__file__).resolve().parents[1] / "docs" / "content" / "reference" / "settings.md"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(markdown, encoding="utf-8")


def main() -> None:
    markdown = render_settings()
    _write_output(markdown)


if __name__ == "__main__":
    main()
