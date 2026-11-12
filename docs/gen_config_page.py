import html
import json
from collections.abc import Iterator

import mkdocs_gen_files
from pydantic.fields import FieldInfo

from ffkit.cli.settings import Settings, env_fields, nested_model

PREFIX = "FFKIT_"


def type_name(field: FieldInfo) -> str:
    """Format a field type for a Markdown table cell."""
    name = str(field.annotation).replace("typing.", "").replace("pathlib.", "")
    name = name.replace("_local.", "").replace("<class '", "").replace("'>", "")
    # A backslash-escaped pipe stays visible inside a code span, so use an HTML entity.
    return f"<code>{html.escape(name).replace('|', '&#124;')}</code>"


def default_value(field: FieldInfo) -> str:
    """Format a field default for a Markdown table cell."""
    if field.is_required():
        return "required"
    value = field.get_default(call_default_factory=True)
    return "—" if value is None else f"`{json.dumps(value, default=str)}`"


def table(rows: Iterator[tuple[str, FieldInfo]]) -> list[str]:
    """Build a configuration table from setting fields."""
    lines = ["| Variable | Type | Default | Description |", "| --- | --- | --- | --- |"]

    for variable, field in rows:
        description = field.description or ""
        lines.append(
            f"| `{variable}` | {type_name(field)} | {default_value(field)} | {description} |",
        )

    return lines


lines = [
    "# Configuration",
    "",
    f"This page is generated from `ffkit.cli.settings.Settings`. The `ffkit` command reads "
    f"`{PREFIX}*` environment variables and `.env` in the working directory; the process "
    "environment wins. The library itself does not read them. "
    f"Nested sections use `__`, for example `{PREFIX}LOG__LEVEL`. Empty values use the default.",
]

top_level = [
    (variable, field)
    for variable, field in env_fields()
    if "__" not in variable.removeprefix(PREFIX)
]
if top_level:
    lines += ["", "## Application", "", *table(iter(top_level))]

for name, field in Settings.model_fields.items():
    section = nested_model(field)
    if section is None:
        continue
    lines += ["", f"## {name.capitalize()}", "", (section.__doc__ or "").strip(), ""]
    lines += table(env_fields(section, f"{PREFIX}{name.upper()}__"))

with mkdocs_gen_files.open("configuration.md", "w") as fd:
    fd.write("\n".join(lines) + "\n")

mkdocs_gen_files.set_edit_path("configuration.md", "../src/ffkit/cli/settings.py")
