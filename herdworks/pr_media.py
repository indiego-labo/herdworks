"""Publish only the visual files selected by the independent evidence reviewer."""
import hashlib
import json
import os
from pathlib import Path
import re
import stat

from .runs import git

IMAGES = {".png", ".jpg", ".jpeg", ".gif", ".webp"}
VIDEOS = {".mp4", ".mov", ".webm"}
MAX_BYTES = 10_000_000
MAX_FILES = 50


def plain_markdown(value):
    # Captions and limitations are plain text, never additional Markdown or HTML.
    return re.sub(r"([\\\[\]<>\x26_*\x60#!~])", r"\\\1", " ".join(value.split()))


def reviewed_media(verifier, review, staging):
    manifest = review.parent / "visuals.json"
    if not manifest.exists() and not manifest.is_symlink():
        return [], []
    if (manifest.is_symlink() or not manifest.is_file()
            or not verifier.stat().st_mtime_ns <= manifest.stat().st_mtime_ns <= review.stat().st_mtime_ns):
        raise ValueError("visuals.json must be saved by the evidence reviewer before review.md")
    data = json.loads(manifest.read_text())
    if not isinstance(data, dict):
        raise ValueError("visuals.json must contain media and unavailable lists")
    entries, unavailable = data.get("media", []), data.get("unavailable", [])
    if (not isinstance(entries, list) or len(entries) > MAX_FILES or not isinstance(unavailable, list)
            or any(not isinstance(note, str) or not note.strip() for note in unavailable)):
        raise ValueError("visuals.json must contain up to 50 media entries and a list of unavailable reasons")

    assets = []
    seen = set()
    for entry in entries:
        if not isinstance(entry, dict):
            raise ValueError("each visual entry must name a file, caption, source and SHA-256")
        name, caption, source, digest = (entry.get(key) for key in ("file", "caption", "source", "sha256"))
        if (not isinstance(name, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", name)
                or Path(name).suffix not in IMAGES | VIDEOS or name in seen
                or not isinstance(caption, str) or not caption.strip()
                or source not in ("live", "stand-in")
                or not isinstance(digest, str) or not re.fullmatch(r"[a-f0-9]{64}", digest)):
            raise ValueError("invalid, unsupported or duplicate visual entry in visuals.json")
        seen.add(name)
        label = ("Stand-in: " if source == "stand-in" else "") + caption
        try:
            content = read_media(verifier.parent / "evidence", name)
        except OSError:
            unavailable.append(f"{label} could not be read from the verifier’s evidence.")
            continue
        if not content or len(content) > MAX_BYTES or hashlib.sha256(content).hexdigest() != digest:
            unavailable.append(f"{label} was empty, over 10 MB, or changed after evidence review.")
            continue
        file = staging / f"visual-{len(assets)+1}{Path(name).suffix}"
        file.write_bytes(content)
        assets.append((file, label))
    return assets, unavailable


def read_media(directory, name):
    folder = os.open(directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=folder)
        with os.fdopen(fd, "rb") as stream:
            if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
                return b""
            return stream.read(MAX_BYTES + 1)
    finally:
        os.close(folder)


def visual_section(repo, assets, unavailable, attachments):
    """Return the body section, gh attachment flags, and any durable Git ref to push."""
    if not assets and not unavailable:
        return "", [], None
    lines = ["## Visual evidence"]
    flags = []
    ref = None
    if not attachments:
        images = [file for file, _ in assets if file.suffix in IMAGES]
        if images:
            blobs = [(file.name, git(repo, "hash-object", "-w", "--no-filters", "--", file))
                     for file in images]
            tree = git(repo, "mktree", input="".join(f"100644 blob {blob}\t{name}\n" for name, blob in blobs))
            commit = git(repo, "commit-tree", tree, "--no-gpg-sign", "-m", "Record pull request visual evidence")
            ref = f"{commit}:refs/tags/hw-evidence/{commit}"
    for file, caption in assets:
        label = plain_markdown(caption)
        video = file.suffix in VIDEOS
        if attachments:
            flags.extend(("--attach", str(file)))
            lines.extend((label, f"![{'' if video else label}]({file.name})"))
        elif video:
            unavailable.append(f"{caption} stayed in Project evidence. This publisher needs an animated GIF preview or GitHub CLI attachment support to show it inline.")
        else:
            lines.extend((label, f"![{label}](../blob/{commit}/{file.name}?raw=true)"))
    if unavailable:
        lines.append("\n".join(f"- {plain_markdown(note)}" for note in unavailable))
    return "\n\n".join(lines) + "\n\n", flags, ref
