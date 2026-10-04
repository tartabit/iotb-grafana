import argparse
import json
import re
import sys
from pathlib import Path


VARIABLE_REF = re.compile(
    r"\$(?:\{(?P<braced>[A-Za-z_][A-Za-z0-9_]*)(?::[^}]*)?\}|"
    r"(?P<plain>[A-Za-z_][A-Za-z0-9_]*))"
)
TRIGGER_METRIC = re.compile(
    r"\b(?P<metric>iotbridge_trigger_engine_[A-Za-z0-9_]+)"
    r"(?P<labels>\{(?:\$\{[^}]+\}|[^{}])*\})?"
)
VALUE_CHANGING_MAP_JOIN = re.compile(
    r"\+\s+on\([^)]*\).*iotbridge_(?:account|service|trigger)_map"
)
NAME_MAP = re.compile(r"iotbridge_(?:account|service|trigger)_map")


def walk_panels(items):
    for panel in items:
        yield panel
        yield from walk_panels(panel.get("panels", []))


def variable_references(value):
    if not isinstance(value, str):
        return set()
    return {
        match.group("braced") or match.group("plain")
        for match in VARIABLE_REF.finditer(value)
    }


def add_error(errors, path, context, message):
    errors.append(f"{path}: {context}: {message}")


def validate_dashboard(path):
    errors = []
    try:
        with path.open(encoding="utf-8") as handle:
            payload = json.load(handle)
    except (OSError, json.JSONDecodeError) as exc:
        return [f"{path}: invalid JSON: {exc}"]

    dashboard = payload.get("dashboard")
    if not isinstance(dashboard, dict):
        return [f"{path}: missing dashboard object"]

    for field in ("title", "uid"):
        if not dashboard.get(field):
            add_error(errors, path, "dashboard", f"missing {field}")

    variables = dashboard.get("templating", {}).get("list", [])
    variable_names = [variable.get("name") for variable in variables]
    seen_variables = set()
    for name in variable_names:
        if not name:
            add_error(errors, path, "dashboard", "template variable is missing a name")
        elif name in seen_variables:
            add_error(errors, path, "dashboard", f"duplicate template variable {name!r}")
        seen_variables.add(name)

    allowed_variables = set(variable_names)
    for variable in variables:
        context = f"variable {variable.get('name', '<unnamed>')!r}"
        values = [variable.get("definition"), variable.get("query")]
        if isinstance(variable.get("query"), dict):
            values.append(variable["query"].get("query"))
        for value in values:
            for reference in variable_references(value):
                if not reference.startswith("__") and reference not in allowed_variables:
                    add_error(errors, path, context, f"undefined variable ${reference}")

    panel_ids = set()
    marked_panel_ids = set()
    for panel in walk_panels(dashboard.get("panels", [])):
        panel_id = panel.get("id")
        title = panel.get("title") or f"panel {panel_id}"
        context = f"panel {panel_id} ({title})"
        if panel_id is None:
            add_error(errors, path, context, "missing panel id")
        elif panel_id in panel_ids:
            add_error(errors, path, context, f"duplicate panel id {panel_id}")
        panel_ids.add(panel_id)

        if title == "Panel Title":
            add_error(errors, path, context, "placeholder panel title")
        if str(title).startswith("(x) "):
            marked_panel_ids.add(panel_id)
        content = panel.get("options", {}).get("content", "")
        if "For markdown syntax help" in content or content.strip() == "# Title":
            add_error(errors, path, context, "placeholder panel content")

        for target in panel.get("targets", []):
            expr = target.get("expr")
            if not expr:
                continue
            for reference in variable_references(expr):
                if not reference.startswith("__") and reference not in allowed_variables:
                    add_error(errors, path, context, f"undefined variable ${reference}")
            if VALUE_CHANGING_MAP_JOIN.search(expr):
                add_error(errors, path, context, "name-map join uses + and changes the value")
            if "group_left" in expr and NAME_MAP.search(expr) and "max by" not in expr:
                add_error(errors, path, context, "name-map join is not deduplicated with max by")

            if dashboard.get("uid") == "a97efa86-05fd-4950-adf0-a67806a01efa":
                for match in TRIGGER_METRIC.finditer(expr):
                    labels = match.group("labels") or ""
                    if 'accountId=~"${accountId:regex}"' not in labels:
                        add_error(
                            errors,
                            path,
                            context,
                            f"{match.group('metric')} is missing the account filter",
                        )
                    if 'triggerId=~"${triggerId:regex}"' not in labels:
                        add_error(
                            errors,
                            path,
                            context,
                            f"{match.group('metric')} is missing the trigger filter",
                        )

    if dashboard.get("uid") == "a97efa86-05fd-4950-adf0-a67806a01efa":
        expected_marked = {2, 3, 7}
        if marked_panel_ids != expected_marked:
            add_error(
                errors,
                path,
                "dashboard",
                f"(x) panels must be exactly {sorted(expected_marked)}, got {sorted(marked_panel_ids)}",
            )

    return errors


def main():
    parser = argparse.ArgumentParser(description="Validate exported Grafana dashboards.")
    parser.add_argument(
        "folder",
        nargs="?",
        default="library/dashboards",
        type=Path,
        help="Folder containing dashboard JSON files (default: library/dashboards)",
    )
    args = parser.parse_args()

    paths = sorted(args.folder.glob("*.json"))
    if not paths:
        print(f"No dashboard JSON files found in {args.folder}", file=sys.stderr)
        return 1

    errors = []
    for path in paths:
        errors.extend(validate_dashboard(path))

    if errors:
        print("Dashboard validation failed:", file=sys.stderr)
        for error in errors:
            print(f"- {error}", file=sys.stderr)
        return 1

    print(f"Validated {len(paths)} dashboards in {args.folder}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
