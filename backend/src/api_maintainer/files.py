import difflib
import hashlib
import json
import os
import re
from pathlib import Path, PurePosixPath


def atomic_write(path: Path, value: str):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + ".tmp")
    temp.write_text(value)
    os.replace(temp, path)


def digest(raw: bytes):
    return hashlib.sha256(raw).hexdigest()


def tree_hash(root):
    h = hashlib.sha256()
    for path in sorted(root.rglob("*")):
        if path.is_symlink():
            raise ValueError("Symlinks are not allowed in source snapshots.")
        if path.is_file():
            h.update(str(path.relative_to(root)).encode() + b"\0" + path.read_bytes() + b"\0")
    return h.hexdigest()


def safe_path(root, name, allowed):
    p = PurePosixPath(name)
    if "\\" in name or p.is_absolute() or ".." in p.parts or name not in allowed:
        raise ValueError("Path is outside the allowed source/input files.")
    root = root.resolve()
    target = root
    for component in p.parts:
        target = target / component
        if target.is_symlink():
            raise ValueError("Symlinks are forbidden inside the workspace.")
    if not target.resolve().is_relative_to(root):
        raise ValueError("Path escaped the workspace.")
    return target


def source_diff(original, workspace):
    result, edited = [], []
    for old in sorted(p for p in original.rglob("*") if p.is_file()):
        rel = str(old.relative_to(original))
        before, after = old.read_text(), (workspace / rel).read_text()
        if before != after:
            edited.append(rel)
            result.extend(
                line if line.endswith("\n") else line + "\n\\ No newline at end of file\n"
                for line in difflib.unified_diff(
                    before.splitlines(True), after.splitlines(True), fromfile="a/" + rel, tofile="b/" + rel
                )
            )
    return "".join(result), edited


_EDIT_KEYS = {
    "path": ("path", "file", "file_path", "filename", "filepath"),
    "find": ("find", "search", "old", "old_str", "old_string", "old_text", "from"),
    "replace": ("replace", "new", "new_str", "new_string", "new_text", "to", "with"),
}


def _normalise_edits(edits):
    """Accept the shapes models actually emit, then validate strictly.

    Tool arguments arrive as a JSON string as often as a list, single edits arrive
    unwrapped, and key names vary by whichever editing tool the model has seen. None
    of that is a safety property, so normalise it rather than spending an attempt.
    """
    if isinstance(edits, str):
        try:
            edits = json.loads(edits)
        except ValueError:
            raise ValueError(
                "edits must be a list of {path, find, replace} objects, not a plain string."
            ) from None
    if isinstance(edits, dict):
        # A single unwrapped edit, or {"edits": [...]}.
        for key in ("edits", "changes", "patches"):
            if isinstance(edits.get(key), list):
                edits = edits[key]
                break
        else:
            edits = [edits]
    if not isinstance(edits, list):
        return edits
    out = []
    for edit in edits:
        if not isinstance(edit, dict):
            out.append(edit)
            continue
        mapped = {}
        for canonical, aliases in _EDIT_KEYS.items():
            for alias in aliases:
                if alias in edit:
                    value = edit[alias]
                    # Some models send the body as a list of lines.
                    if isinstance(value, list) and all(isinstance(v, str) for v in value):
                        value = "\n".join(value)
                    mapped[canonical] = value
                    break
        out.append(mapped or edit)
    return out


def apply_edits(workspace, edits, allowed):
    """Exact-text replacement in existing approved files.

    Each edit locates itself by a unique text match rather than by line number.
    A unique match is a stronger claim than a position: it is a statement about
    the file rather than about the model's arithmetic, and ambiguity fails loudly
    instead of guessing. Same envelope as apply_unified: approved paths only, no
    shell, fuzzy matching, file creation/deletion or renames; rollback on error.
    """
    edits = _normalise_edits(edits)
    if not isinstance(edits, list) or not edits:
        raise ValueError("Supply a nonempty list of edits, each with path, find and replace.")
    if len(edits) > 50:
        raise ValueError("Supply at most 50 edits per call.")
    budget = sum(
        len(str(e.get("find", ""))) + len(str(e.get("replace", ""))) for e in edits if isinstance(e, dict)
    )
    if budget > 128 * 1024:
        raise ValueError("Edits exceed 128 KiB of text in total.")
    proposed, originals = {}, {}
    for n, edit in enumerate(edits, 1):
        if not isinstance(edit, dict):
            raise ValueError(f"Edit {n} must be an object with path, find and replace.")
        name, find, replace = edit.get("path"), edit.get("find"), edit.get("replace")
        if not isinstance(name, str) or not isinstance(find, str) or not isinstance(replace, str):
            raise ValueError(f"Edit {n}: path, find and replace must all be strings.")
        if not find:
            raise ValueError(f"Edit {n}: find must be nonempty so the edit can be located.")
        if find == replace:
            raise ValueError(f"Edit {n}: find and replace are identical, so the edit changes nothing.")
        # Read tools expose a virtual source/ prefix; edits may use that same path.
        if name not in allowed and name.startswith("source/"):
            name = name.removeprefix("source/")
        target = safe_path(workspace, name, allowed)
        if name not in proposed:
            proposed[name] = originals[name] = target.read_text()
        body = proposed[name]
        seen = body.count(find)
        if seen == 0:
            raise ValueError(
                f"Edit {n}: the find text is not present in {name}. Re-read the file and copy its "
                "exact text including indentation; do not add backslash escapes to quotes."
            )
        if seen > 1:
            raise ValueError(
                f"Edit {n}: the find text appears {seen} times in {name}, so its target is ambiguous. "
                "Include enough surrounding lines to match exactly one place."
            )
        proposed[name] = body.replace(find, replace, 1)
    for name, body in proposed.items():
        # A replacement must not silently rewrite the final byte of the delivered source.
        if body and not body.endswith("\n") and originals[name].endswith("\n"):
            proposed[name] = body + "\n"
    try:
        for name, value in proposed.items():
            atomic_write(workspace / name, value)
    except BaseException:
        for name, value in originals.items():
            atomic_write(workspace / name, value)
        raise
    return tree_hash(workspace)


def apply_unified(workspace, patch, allowed):
    """Strict existing-file unified diff. Validate every hunk before publishing changes.

    Workspace is owned by one serialized worker; rollback on filesystem errors.
    No shell, fuzzy matching, file creation/deletion or git directives.
    """
    if not patch or len(patch.encode()) > 128 * 1024:
        raise ValueError("Supply a nonempty unified diff of at most 128 KiB.")
    lines, i, proposed, originals = patch.splitlines(True), 0, {}, {}
    while i < len(lines):
        if not lines[i].startswith("--- a/") or i + 1 >= len(lines) or not lines[i + 1].startswith("+++ b/"):
            raise ValueError("Expected --- a/path and +++ b/path headers.")
        name = lines[i][6:].rstrip("\n")
        if name != lines[i + 1][6:].rstrip("\n"):
            raise ValueError("Renames and duplicate file sections are unsupported.")
        # Read tools expose a virtual source/ prefix; patches may use that same path.
        if name not in allowed and name.startswith("source/"):
            name = name.removeprefix("source/")
        if name in proposed:
            raise ValueError("Renames and duplicate file sections are unsupported.")
        target = safe_path(workspace, name, allowed)
        old = target.read_text().splitlines(True)
        out, cursor, hunks = [], 0, 0
        i += 2
        while i < len(lines) and lines[i].startswith("@@"):
            match = re.fullmatch(r"@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@[^\n]*\n?", lines[i])
            if not match:
                raise ValueError("Invalid hunk header.")
            start, count, newstart, newcount = (
                int(match[1]),
                int(match[2] or 1),
                int(match[3]),
                int(match[4] or 1),
            )
            offset = start - 1 if count else start
            if offset < cursor or offset > len(old):
                raise ValueError("Overlapping or out-of-range hunk.")
            out.extend(old[cursor:offset])
            cursor = offset
            if (newstart - 1 if newcount else newstart) != len(out):
                raise ValueError("New hunk offset does not match.")
            consumed = produced = 0
            i += 1
            while i < len(lines) and lines[i][:1] in (" ", "+", "-") and not lines[i].startswith("--- a/"):
                line, kind = lines[i][1:], lines[i][0]
                if kind in (" ", "-"):
                    if cursor >= len(old) or old[cursor] != line:
                        found = old[cursor].rstrip("\n")[:90] if cursor < len(old) else "<past end of file>"
                        raise ValueError(
                            f"Patch context does not match {name} at line {cursor + 1}: the file has "
                            f"{found!r} but the patch supplied {line.rstrip(chr(10))[:90]!r}. Re-read the "
                            "file and copy its exact text; do not add backslash escapes to quotes."
                        )
                    cursor += 1
                    consumed += 1
                if kind in (" ", "+"):
                    out.append(line)
                    produced += 1
                i += 1
            if (consumed, produced) != (count, newcount):
                raise ValueError(
                    f"Hunk '@@ -{start},{count} +{newstart},{newcount} @@' in {name} declares {count} "
                    f"original and {newcount} new lines, but its body contains {consumed} and {produced}. "
                    "Set each count to the number of lines you actually wrote: originals are the ' ' and "
                    "'-' lines, new are the ' ' and '+' lines."
                )
            hunks += 1
        if not hunks:
            raise ValueError("Each file needs a hunk.")
        out.extend(old[cursor:])
        body = "".join(out)
        # Only an explicit "\ No newline at end of file" marker means "drop the trailing
        # newline", and this parser does not accept one. A patch whose last line simply
        # lacks "\n" must not silently rewrite the final byte of the delivered source.
        if body and not body.endswith("\n") and (not old or old[-1].endswith("\n")):
            body += "\n"
        proposed[name], originals[name] = body, "".join(old)
    try:
        for name, value in proposed.items():
            atomic_write(workspace / name, value)
    except BaseException:
        for name, value in originals.items():
            atomic_write(workspace / name, value)
        raise
    return tree_hash(workspace)
