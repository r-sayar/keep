---
name: keep-to-csv
description: "Fetch the user's notes from the Keep web app's Supabase database and write them to a CSV file. Use when the user says 'keep to csv', 'export my keep notes', 'pull notes from keep', '/keep-to-csv', or asks to turn their note app contents into a spreadsheet."
allowed-tools: [Read, Write, Bash]
---

# Keep → CSV

Pulls the user's notes from Supabase (the Keep web app's backend) and writes them to a CSV the user can open in any spreadsheet tool.

## Credentials

Hardcoded — these are publishable keys, safe to embed:

- `SUPABASE_URL`: `https://sywglobxvtxayvelhunb.supabase.co`
- `SUPABASE_KEY`: `sb_publishable_92UpBhuxnldvBH5hXGiy7Q_voxEzcsc`

The `notes` table has RLS allowing the anon/publishable key to read rows where `user_id='default'`.

## Process

1. **Fetch** all notes with curl (sorted newest first):

   ```bash
   curl -s \
     "https://sywglobxvtxayvelhunb.supabase.co/rest/v1/notes?select=id,created_at,title,body&user_id=eq.default&order=created_at.desc" \
     -H "apikey: sb_publishable_92UpBhuxnldvBH5hXGiy7Q_voxEzcsc" \
     -H "Authorization: Bearer sb_publishable_92UpBhuxnldvBH5hXGiy7Q_voxEzcsc"
   ```

2. **Parse** the JSON response. If empty, tell the user "No notes" and stop.

3. **Write CSV** to `~/Downloads/keep-notes-YYYY-MM-DD.csv` with columns: `id,created_at,title,body`.
   - RFC 4180 escaping: wrap every field in `"..."`, double internal quotes, newlines inside quoted fields are fine.
   - Use a small Python or jq script — don't roll string concatenation by hand.

4. **Confirm** to the user: row count, absolute path. Offer `open <path>` to launch it.

## Reference Python (one-liner you can adapt)

```python
import json, csv, sys, pathlib, datetime, urllib.request

URL = "https://sywglobxvtxayvelhunb.supabase.co/rest/v1/notes?select=id,created_at,title,body&user_id=eq.default&order=created_at.desc"
KEY = "sb_publishable_92UpBhuxnldvBH5hXGiy7Q_voxEzcsc"

req = urllib.request.Request(URL, headers={"apikey": KEY, "Authorization": f"Bearer {KEY}"})
notes = json.loads(urllib.request.urlopen(req).read())
if not notes:
    print("No notes"); sys.exit(0)

out = pathlib.Path.home() / "Downloads" / f"keep-notes-{datetime.date.today()}.csv"
with out.open("w", newline="") as f:
    w = csv.DictWriter(f, fieldnames=["id", "created_at", "title", "body"], quoting=csv.QUOTE_ALL)
    w.writeheader()
    w.writerows(notes)
print(f"Wrote {len(notes)} rows to {out}")
```
