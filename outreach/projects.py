"""Projects: one account, many use cases. A project names a handbook, a set of inputs its targets
need, and a template. The engine (research -> draft -> approve -> send -> track) is shared; only the
project's configuration changes what gets drafted.

This module is PURE: it parses and validates project rows and selects among them. It never reads the
Sheet, calls a model, or writes anything. The AI is not trained here - a project's handbook is its
configuration, read at draft time like any other grounding input.
"""

import json

# Known project kinds. "custom" lets a founder define one whose inputs/template they supply.
TYPES = ("lead", "referral", "investor", "custom")

# The Projects tab columns (one row per project). Offer and input schema are JSON in a single cell.
TAB = "Projects"
HEADER = ["Project ID", "Name", "Type", "Handbook doc ID", "Offer JSON", "Input schema",
          "Created at (UTC)"]

# Every existing lead belongs to this project id until it is assigned another, so a single-project
# account keeps working unchanged when the Project column is added.
DEFAULT_ID = "P-default"


class ProjectError(Exception):
    """A project row is malformed; it is reported, never guessed into shape."""


def _json_or(default, raw):
    raw = (raw or "").strip()
    if not raw:
        return default
    try:
        return json.loads(raw)
    except (ValueError, TypeError):
        raise ProjectError(f"invalid JSON in a project cell: {raw[:40]}")


def parse(row):
    """One project dict from a Projects-tab row (a {header: value} mapping), or ProjectError.

    A project needs at least an id, a name and a known type. `offer` and `input_schema` default to an
    empty object / list when their cell is blank; `handbook_doc_id` may be blank (set later)."""
    project_id = (row.get("Project ID") or "").strip()
    name = (row.get("Name") or "").strip()
    kind = (row.get("Type") or "").strip().lower()
    if not project_id:
        raise ProjectError("a project row has no Project ID")
    if not name:
        raise ProjectError(f"{project_id}: a project has no Name")
    if kind not in TYPES:
        raise ProjectError(f"{project_id}: unknown project type {kind!r} (expected one of {', '.join(TYPES)})")
    schema = _json_or([], row.get("Input schema"))
    if not isinstance(schema, list) or not all(isinstance(f, str) for f in schema):
        raise ProjectError(f"{project_id}: Input schema must be a JSON list of field names")
    offer = _json_or({}, row.get("Offer JSON"))
    if not isinstance(offer, dict):
        raise ProjectError(f"{project_id}: Offer JSON must be a JSON object")
    return {
        "id": project_id,
        "name": name,
        "type": kind,
        "handbook_doc_id": (row.get("Handbook doc ID") or "").strip(),
        "offer": offer,
        "input_schema": schema,
        "created_at": (row.get("Created at (UTC)") or "").strip(),
    }


def parse_all(rows):
    """Every valid project, keyed by id. A malformed row raises - a project list is configuration and
    must be read exactly, not partially."""
    projects = {}
    for row in rows:
        project = parse(row)
        if project["id"] in projects:
            raise ProjectError(f"duplicate Project ID {project['id']}")
        projects[project["id"]] = project
    return projects


def default_project(settings=None):
    """The implicit project a single-project account runs, built from the current settings so existing
    leads (with a blank Project cell) keep drafting from the configured handbook. A Projects tab is not
    required until the founder defines more than one project."""
    settings = settings or {}
    return {
        "id": DEFAULT_ID,
        "name": "Default outreach",
        "type": "lead",
        "handbook_doc_id": (settings.get("handbook_doc_id") or "").strip(),
        "offer": {},
        "input_schema": [],
        "created_at": "",
    }


def project_of(projects, target_row, *, default_id=DEFAULT_ID):
    """The project a target (a lead row) belongs to: its `Project` cell, or the default project.
    Returns the project dict, or None when the named project does not exist."""
    wanted = (target_row.get("Project") or "").strip() or default_id
    return projects.get(wanted)


def handbook_doc_for(target_row, projects, settings=None):
    """The Drive handbook document id a lead should draft from: its project's handbook, or - when the
    project has none configured - the settings handbook. This is the one decision that makes drafting
    project-aware; the drafting pipeline loads the handbook from the id it returns, nothing else changes.
    Returns "" when neither is set (the caller then refuses, never guesses a handbook)."""
    project = project_of(projects, target_row)
    if project and project.get("handbook_doc_id"):
        return project["handbook_doc_id"]
    return ((settings or {}).get("handbook_doc_id") or "").strip()
