"""Keep preference memory and private intake text out of the oversight payload."""
import json

PRIVATE_ACTIONS = {"extract_constraints", "clarify_constraints", "correct_constraints", "route_message"}


def audit_payload(value, action=""):
    if isinstance(value, list):
        return [audit_payload(v, action) for v in value]
    if not isinstance(value, dict):
        return value
    out = {}
    for key, item in value.items():
        if "preference" in key.lower():
            out[key] = "[private preference data omitted]"
        elif key in {"prompt", "raw"} and action in PRIVATE_ACTIONS:
            out[key] = "[private shopper input omitted]"
        elif isinstance(item, str):
            try:
                parsed = json.loads(item)
            except (ValueError, TypeError):
                out[key] = item
            else:
                out[key] = json.dumps(audit_payload(parsed, action)) if isinstance(parsed, (dict, list)) else item
        else:
            out[key] = audit_payload(item, action)
    return out
