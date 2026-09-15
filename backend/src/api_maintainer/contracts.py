import json
import re

import yaml
from openapi_spec_validator import OpenAPIV30SpecValidator


class InputError(ValueError):
    pass


def pointer_get(document, pointer):
    if not isinstance(pointer, str):
        raise InputError("References must be local JSON pointer strings.")
    if pointer == "#":
        return document
    if not pointer.startswith("#/"):
        raise InputError("Only references within the supplied contract are supported.")
    value = document
    try:
        for part in pointer[2:].split("/"):
            part = part.replace("~1", "/").replace("~0", "~")
            value = value[int(part)] if isinstance(value, list) else value[part]
        return value
    except (KeyError, ValueError, IndexError, TypeError) as exc:
        raise InputError(f"Unresolved JSON pointer: {pointer}") from exc


def parse_contract(raw: bytes):
    if len(raw) > 1024 * 1024:
        raise InputError("Contract exceeds 1 MiB.")
    try:
        doc = yaml.safe_load(raw)
    except (yaml.YAMLError, UnicodeError, RecursionError) as exc:
        raise InputError("Contract must be valid JSON or safe YAML.") from exc
    if not isinstance(doc, dict) or not re.fullmatch(r"3\.0\.\d+", str(doc.get("openapi", ""))):
        raise InputError("Only OpenAPI 3.0.x contracts are supported.")
    seen, nodes = set(), 0

    def walk(value, depth=0):
        nonlocal nodes
        nodes += 1
        if depth > 60 or nodes > 30000:
            raise InputError("Contract nesting or complexity exceeds supported limits.")
        if isinstance(value, (dict, list)):
            if id(value) in seen:
                raise InputError("YAML aliases/cycles are unsupported; expand them first.")
            seen.add(id(value))
        if isinstance(value, dict):
            if not all(isinstance(k, str) for k in value):
                raise InputError("Object keys must be strings.")
            if "$ref" in value:
                pointer_get(doc, value["$ref"])
            for child in value.values():
                walk(child, depth + 1)
        elif isinstance(value, list):
            for child in value:
                walk(child, depth + 1)

    walk(doc)
    try:
        OpenAPIV30SpecValidator(doc).validate()
        json.dumps(doc, allow_nan=False)
    except Exception as exc:
        raise InputError("Invalid OpenAPI document; check info, paths, schemas and references.") from exc
    return doc


def structural_diff(old, new):
    """Structural facts only: never infer a semantic rename from add/remove."""
    changes = []

    def walk(a, b, path="#"):
        if isinstance(a, dict) and isinstance(b, dict):
            for key in sorted(a.keys() | b.keys()):
                p = path + "/" + key.replace("~", "~0").replace("/", "~1")
                if key not in b:
                    changes.append(dict(kind="removed", path="inputs/old.json", pointer=p, before=a[key]))
                elif key not in a:
                    changes.append(dict(kind="added", path="inputs/new.json", pointer=p, after=b[key]))
                else:
                    walk(a[key], b[key], p)
        elif a != b:
            changes.append(dict(kind="changed", path="inputs/new.json", pointer=path, before=a, after=b))

    walk(old, new)
    return changes
