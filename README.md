# Keep

A minimal, fast note-taking PWA backed by Supabase. Installable on desktop and Android. Importable from a Google Keep takeout. Exportable to CSV from Claude Desktop / Claude Code via a custom skill.

**Live demo:** https://keep-jet.vercel.app

![screenshot](docs/screenshot.png) <!-- optional -->

---

## Features

- **Email magic-link login** (Supabase Auth) — multi-user, RLS-enforced; each user only sees their own notes
- **List view** with composer at top, newest-first
- **Auto-focus** the note field on open — start typing immediately
- **Search** with server-side `ILIKE` over title + body, backed by a pg_trgm trigram index (instant on 4000+ notes)
- **Pagination** (50/page, "Load more" button)
- **Archive toggle** (hidden by default)
- **Pinned notes first**, then newest
- **Labels** rendered as chips, **source URLs** as small links
- **Keyboard shortcuts**: `n` focuses composer, `/` focuses search, `⌘/Ctrl+Enter` saves
- **PWA**: installable on iOS, Android, macOS, Windows; works offline (read cache)
- **Web Share Target**: Android share sheet → Keep creates a prefilled note
- **App shortcut**: long-press home-screen icon → "New note" jumps to composer
- **Google Keep import**: bulk-import from a Google Takeout zip (4000+ notes, idempotent re-import)
- **Image attachments**: from a Keep takeout, copied to a local folder; each affected note gets a footer line pointing to the on-disk path
- **CSV export via Claude**: a custom skill (`/keep-to-csv`) that fetches notes from Supabase and writes a CSV to `~/Downloads/`

---

## Tech stack

| Layer | Choice |
|---|---|
| Frontend | Single `index.html`, vanilla JS (no build step), Supabase JS client via ESM CDN |
| DB | Supabase (Postgres + REST + RLS + pg_trgm) |
| Hosting | Vercel (static) |
| Mobile | PWA — Add to Home Screen, or wrap to APK via [PWABuilder.com](https://www.pwabuilder.com) |
| Claude integration | Skill (`SKILL.md`) installable into Claude Desktop or Claude Code |

---

## Quick start (your own instance)

### 1. Supabase

1. Create a free project at [supabase.com](https://supabase.com).
2. From **Project Settings → API**, copy the **Project URL** and the **publishable** key (`sb_publishable_…`).
3. In the SQL editor, run the schema:

   ```sql
   create table public.notes (
     id uuid primary key default gen_random_uuid(),
     user_id text not null default 'default',
     title text not null default '',
     body text not null default '',
     pinned boolean not null default false,
     archived boolean not null default false,
     color text not null default 'DEFAULT',
     labels text[] not null default '{}',
     source_url text,
     google_id text,
     created_at timestamptz not null default now(),
     updated_at timestamptz not null default now()
   );

   create unique index notes_user_google_id_uniq
     on public.notes (user_id, google_id);
   create index notes_user_archived_pinned_created_idx
     on public.notes (user_id, archived, pinned desc, created_at desc);

   create schema if not exists extensions;
   create extension if not exists pg_trgm with schema extensions;
   create index notes_title_trgm_idx on public.notes using gin (title extensions.gin_trgm_ops);
   create index notes_body_trgm_idx  on public.notes using gin (body  extensions.gin_trgm_ops);

   alter table public.notes enable row level security;

   -- Multi-user mode: each authenticated user can CRUD only their own rows.
   -- user_id is the Supabase auth.uid() as text.
   create policy "auth users own their notes"
     on public.notes
     for all
     to authenticated
     using (auth.uid()::text = user_id)
     with check (auth.uid()::text = user_id);
   ```

4. **URL config (required)** — Authentication → URL Configuration:
   - **Site URL**: `https://YOUR_APP.vercel.app`
   - **Redirect URLs**: add `https://YOUR_APP.vercel.app/**`
   - For local dev also add `http://localhost:8766/**`

5. In `index.html`, replace the two constants near the top of `<script type="module">`:

   ```js
   const SUPABASE_URL = "https://YOUR_PROJECT.supabase.co";
   const SUPABASE_KEY = "sb_publishable_...";
   ```

   Do the same in `import_takeout.py` and `skill/keep-to-csv/SKILL.md` if you plan to use them.

> The publishable key is safe to ship in the browser — RLS limits what it can do.

### 2. Vercel deploy

```bash
npx vercel deploy --prod
```

Or push to GitHub and import the repo at [vercel.com/new](https://vercel.com/new) — it auto-detects this as a static project.

### 3. Install on Android

1. Open the deployed URL in Chrome on Android.
2. Menu → **Add to Home screen**.

For a real `.apk`: paste your URL into [PWABuilder.com](https://www.pwabuilder.com) → Package for Stores → Android.

### 4. Install the Claude skill

The skill (`skill/keep-to-csv/SKILL.md`) lets Claude fetch your notes and write them to a CSV.

**Claude Desktop:**

```bash
mkdir -p ~/Library/Application\ Support/Claude/skills
cp -r ./skill/keep-to-csv ~/Library/Application\ Support/Claude/skills/
```

Restart Claude Desktop. Type `/keep-to-csv` in any chat.

**Claude Code:**

```bash
mkdir -p ~/.claude/skills
cp -r ./skill/keep-to-csv ~/.claude/skills/
```

Restart the session.

---

## Importing from a Google Keep takeout

1. Go to [takeout.google.com](https://takeout.google.com), select **Keep**, download the zip.
2. Extract it somewhere. You'll get a `Takeout/Keep/` folder with one `.json` per note plus `.html` mirrors and any image attachments.
3. (Optional) If you want the image attachments referenced, copy them to a stable folder:

   ```bash
   mkdir -p ~/Desktop/keep-attachments
   cp Takeout/Keep/*.{jpg,png} ~/Desktop/keep-attachments/
   ```

   The import script appends a footer to each affected note pointing to this folder.

4. Run the importer:

   ```bash
   python3 import_takeout.py /path/to/Takeout/Keep/
   ```

The script is **idempotent** — uses `google_id` (the JSON filename) as a natural key, so re-running updates instead of duplicating.

What gets imported:

| Source field | Destination |
|---|---|
| `title`, `textContent` | `title`, `body` |
| `createdTimestampUsec`, `userEditedTimestampUsec` | `created_at`, `updated_at` |
| `isPinned`, `isArchived` | `pinned`, `archived` |
| `color` | `color` |
| `labels[].name` | `labels[]` |
| First `annotations[].url` (WEBLINK) | `source_url` |
| `attachments[].filePath` | Footer line in body: `📎 Attachment(s) saved on disk: ~/Desktop/keep-attachments/<file>` |
| `listContent[]` (checklists) | Flattened into body as `[ ]` / `[x]` lines |
| `isTrashed` | Skipped |

---

## Architecture

```
┌─────────────┐     PostgREST      ┌──────────────────┐
│  index.html │ ◄────────────────► │ Supabase Postgres│
│  (browser)  │                    │  + pg_trgm + RLS │
└─────────────┘                    └──────────────────┘
       ▲                                    ▲
       │                                    │
   Add to Home                              │
   Screen / PWA                          curl/REST
       │                                    │
       │                           ┌────────┴─────────┐
   Android / iOS                   │ /keep-to-csv     │
   / macOS                         │ skill (Claude    │
                                   │ Desktop or Code) │
                                   └──────────────────┘
                                            ▲
                                            │
                            python3 import_takeout.py
                            (one-shot bulk import from
                             Google Keep takeout)
```

- All client traffic goes browser → Supabase REST. No backend server, no Vercel functions.
- The `/keep-to-csv` skill is a markdown file describing the procedure; Claude executes it (curl + Python) at invocation time.
- The publishable key is shipped in the HTML; Row Level Security restricts it to rows where `user_id='default'`. To go multi-user, add Supabase Auth and replace the policy with `auth.uid()::text = user_id`.

---

## File map

| File | Purpose |
|---|---|
| `index.html` | The whole web app — UI, Supabase client, search, pagination, share-target |
| `manifest.json` | PWA manifest (icons, install metadata, share_target, app shortcuts) |
| `icon.svg` | App icon (also used as maskable) |
| `sw.js` | Service worker — offline cache, makes the app installable |
| `vercel.json` | Vercel deploy config (cleanUrls, SW headers) |
| `import_takeout.py` | One-shot bulk import from Google Keep takeout (idempotent upsert) |
| `skill/keep-to-csv/SKILL.md` | Claude Desktop / Claude Code skill — fetch notes from Supabase, write CSV |

---

## Roadmap

- [x] List view, composer, delete
- [x] Supabase persistence + RLS
- [x] PWA installable
- [x] Vercel deploy
- [x] CSV export via Claude skill
- [x] Search, pagination, archive toggle
- [x] Google Keep takeout import
- [x] Attachment path footers
- [x] Multi-user (Supabase Auth magic link + per-user RLS)
- [ ] Image attachments uploaded to Supabase Storage instead of local-disk references
- [ ] Inline edit + reorder
- [ ] Color tagging UI

---

## How this was built

This entire project was built in a single Claude Code session by iterating on the user's prompts. The full prompt log appears below for transparency / reproducibility.

<details>
<summary><b>Click to expand the full prompt log (19 prompts)</b></summary>

> **1.** Create a simple, minimalistic google keep tool.
>
> *(interrupted)*
>
> **2.** create a new folder within structure-tool, should be excluded from git
>
> **3.** you decide *(naming the folder)*
>
> **4.** Create a simple, minimalistic google keep tool.
>
> **5.** how can i give you some type of design file after which you orient yourself?
>
> **6.** *(with a screenshot of an unrelated tool)* the output needs to be a markdown file. currently it just looks like two list next to each other, i want to have an arrow or connecting node which visualizes that they belong together. also remove the vertical bars on the left side (you can move them to the right if you want)
>
> **7.** bro tf my project has nothing to do with the structure tool, it's a separate thing / project but should live inside this folder. sorry it was from another chat
>
> **8.**
> 1. it should be a list view
> 2. should store in some DB
> 3. should be deployed
> 4. should have a function to "send to claude". i don't care how. what i want is that claude can then kind of go through it and output it as a csv
>
> create another version which i can use on android as an apk
>
> **9.**
> 1. vercel! i want to use my claude desktop app (so maybe you need to create a skill)
> 2. yea for now, i might want to make it for multiple users later, you can let a subagent at the end try it (but on another worktree)
> 3. is there no other way? for example uploading it to some website and it compiles there or creating a shortcut of a website (or a webapp)
>
> **10.**
> webapp great!
> do a "dry thing"
> and then use the supabase mcp
> https://mcp.supabase.com/mcp
>
> **11.** are you sure i need to add in the desktop_config the mcpservers and not inside the desktop app?
>
> **12.**
> ```
> mkdir -p ~/Library/Application\ Support/Claude/skills
> cp -r ./skill/keep-to-csv ~/Library/Application\ Support/Claude/skills/
> ```
> run this
>
> and this:
> ```
> cd scratch/keep
> npx vercel deploy --prod
> ```
>
> **13.** you can now use the supabase mcp
>
> **14.** can you try skills here?
>
> **15.** currently it's a little bit annoying, although I can download it directly to my desktop the keep app, i don't have the functionality to instantly click one single button and be able to immediately add a note
>
> **16.** `@/Users/rls/Downloads/takeout-20260502T064826Z-3-001.zip` import. add functionalities if necessary
>
> **17.** if you skipped the image attachement add something like "can be found in x path on desktop"
>
> **18.**
> after that
> make a version which i can push to github.
> in the readme include all of the prompts i've sent here in this chat + your current version + supabase setup
>
> **19.** how can claude see the notes? how can i create a scheduled recurring task for this?

</details>

---

## License

MIT — see [LICENSE](LICENSE).
