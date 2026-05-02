#!/usr/bin/env python3
"""Bulk-import a Google Keep takeout into the Supabase notes table.

Usage:
    python3 import_takeout.py /path/to/Takeout/Keep/

Idempotent: uses google_id (the JSON filename without .json) as the natural key.
Re-running won't create duplicates — it will update changed rows.
"""
from __future__ import annotations

import json
import sys
import urllib.request
import urllib.error
from pathlib import Path
from datetime import datetime, timezone
from typing import Optional

SUPABASE_URL = "https://sywglobxvtxayvelhunb.supabase.co"
SUPABASE_KEY = "sb_publishable_92UpBhuxnldvBH5hXGiy7Q_voxEzcsc"
USER_ID = "default"
BATCH = 200  # rows per POST

# Where image attachments live on the user's machine (stable path).
# The web app shows this as a footer on notes that had attachments,
# since we don't (yet) upload them to Supabase Storage.
ATTACHMENT_DIR = "~/Desktop/keep-attachments"


def usec_to_iso(usec: int | None) -> str | None:
    if not usec:
        return None
    return datetime.fromtimestamp(usec / 1_000_000, tz=timezone.utc).isoformat()


def first_url(annotations: list[dict]) -> str | None:
    for a in annotations or []:
        if a.get("source") == "WEBLINK" and a.get("url"):
            return a["url"]
    return None


def to_row(path: Path, data: dict) -> dict | None:
    if data.get("isTrashed"):
        return None

    title = (data.get("title") or "").strip()
    body = data.get("textContent") or ""

    # Checklist notes (only 8 in this takeout) — flatten into body with checkmarks
    list_content = data.get("listContent")
    if list_content and not body:
        lines = []
        for item in list_content:
            mark = "[x]" if item.get("isChecked") else "[ ]"
            lines.append(f"{mark} {item.get('text', '')}")
        body = "\n".join(lines)

    # Image attachments — we don't upload them to Supabase Storage; instead
    # we leave a footer pointing the user to the local file path.
    attachments = data.get("attachments") or []
    if attachments:
        files = [a.get("filePath") for a in attachments if a.get("filePath")]
        if files:
            footer_lines = [f"- {ATTACHMENT_DIR}/{name}" for name in files]
            footer = "\n\n📎 Attachment(s) saved on disk:\n" + "\n".join(footer_lines)
            body = (body + footer) if body else footer.lstrip()

    if not title and not body:
        return None

    labels = [l["name"] for l in (data.get("labels") or []) if l.get("name")]
    created = usec_to_iso(data.get("createdTimestampUsec")) or datetime.now(timezone.utc).isoformat()
    updated = usec_to_iso(data.get("userEditedTimestampUsec")) or created

    return {
        "user_id": USER_ID,
        "google_id": path.stem,
        "title": title,
        "body": body,
        "pinned": bool(data.get("isPinned")),
        "archived": bool(data.get("isArchived")),
        "color": data.get("color") or "DEFAULT",
        "labels": labels,
        "source_url": first_url(data.get("annotations")),
        "created_at": created,
        "updated_at": updated,
    }


def post_batch(rows: list[dict]) -> None:
    body = json.dumps(rows).encode("utf-8")
    req = urllib.request.Request(
        f"{SUPABASE_URL}/rest/v1/notes?on_conflict=user_id,google_id",
        data=body,
        method="POST",
        headers={
            "apikey": SUPABASE_KEY,
            "Authorization": f"Bearer {SUPABASE_KEY}",
            "Content-Type": "application/json",
            "Prefer": "resolution=merge-duplicates,return=minimal",
        },
    )
    try:
        with urllib.request.urlopen(req) as resp:
            if resp.status not in (200, 201, 204):
                print(f"  unexpected status {resp.status}: {resp.read()[:200]}")
    except urllib.error.HTTPError as e:
        print(f"  HTTP {e.code}: {e.read()[:400].decode(errors='replace')}")
        raise


def main() -> None:
    if len(sys.argv) != 2:
        print(__doc__)
        sys.exit(1)
    keep_dir = Path(sys.argv[1])
    json_files = sorted(keep_dir.glob("*.json"))
    print(f"Found {len(json_files)} JSON files in {keep_dir}")

    rows: list[dict] = []
    skipped = 0
    for f in json_files:
        try:
            data = json.loads(f.read_text())
        except Exception as e:
            print(f"  skip parse fail: {f.name}: {e}")
            skipped += 1
            continue
        row = to_row(f, data)
        if row is None:
            skipped += 1
            continue
        rows.append(row)

    print(f"Prepared {len(rows)} rows ({skipped} skipped: trashed or empty)")

    sent = 0
    for i in range(0, len(rows), BATCH):
        chunk = rows[i : i + BATCH]
        post_batch(chunk)
        sent += len(chunk)
        print(f"  upserted {sent}/{len(rows)}")
    print("done")


if __name__ == "__main__":
    main()
