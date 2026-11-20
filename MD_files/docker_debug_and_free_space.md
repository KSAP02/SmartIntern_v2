# Docker on Windows: debugging disk space and freeing it back to Windows

**Use this file when:** C: is running low, Docker Desktop won't start, or
`docker_data.vhdx` looks too big. Part A is the **runbook** (what to do, in order).
Part B is the **record** of the 2026-11-17 session that produced it (what went wrong, why,
what we tried).

Setup this applies to: Docker Desktop 4.99 on **Windows 11 Home**, **WSL 2 backend**,
256 GB C: SSD. Paths use `%LOCALAPPDATA%` (= `C:\Users\<you>\AppData\Local`) and
`%APPDATA%` (= `C:\Users\<you>\AppData\Roaming`).

---

# PART A: RUNBOOK

## A0. The one thing to understand

All of Docker's data (images, containers, build cache, volumes) lives in **one virtual disk
file**: `%LOCALAPPDATA%\Docker\wsl\disk\docker_data.vhdx`.

- It **grows** when Docker needs space.
- It **never shrinks by itself.** `docker ... prune` frees space *inside* the file only;
  Windows doesn't get it back. Pruning can even make the file slightly *bigger*.
- To give space back to Windows you must **prune → TRIM → compact** (A3).

So there are two levels:

| Goal | Do | Effect on C: |
| --- | --- | --- |
| Make room *for Docker* | A2 (prune) | none: the file stays the same size |
| Make room *on C:* | A2 + A3 (prune, TRIM, compact) | the file shrinks, C: gets space back |

## A1. Check where the space is (2 min)

PowerShell:
```powershell
"C: free {0:N1} GB" -f ((Get-PSDrive C).Free/1GB)
"docker_data.vhdx {0:N2} GB" -f ((Get-Item "$env:LOCALAPPDATA\Docker\wsl\disk\docker_data.vhdx").Length/1GB)
wsl -l -v
```

Git Bash (Docker must be running):
```bash
docker system df          # what's inside: Images / Containers / Local Volumes / Build Cache
docker system df -v       # per item
```

Read it like this:
- **vhdx much bigger than `docker system df` totals** → space is trapped in the file → A3.
- **Build Cache large** (several GB) → the usual culprit; safe to clear.
- **Many images / stopped containers from old projects** → remove them.

If C: is so full that Docker won't start (< ~2 GB free): empty the Recycle Bin, clear
`%TEMP%`, run Disk Cleanup, or remove an unused WSL distro (`wsl --unregister <name>`,
**deletes that distro's files**, export first with `wsl --export <name> D:\backup.tar`).
Never unregister `docker-desktop`.

## A2. Prune inside Docker (safe: everything here rebuilds from code)

```bash
docker builder prune -a -f       # build cache: usually the biggest
docker container prune -f        # stopped containers
docker image prune -a -f         # images not used by any container
docker system df                 # confirm
```

To keep only certain projects' containers (example: aeris + smartintern_v2):
```bash
ids=$(docker ps -a --format '{{.ID}} {{.Label "com.docker.compose.project"}}' \
      | awk '$2!="aeris" && $2!="smartintern_v2" {print $1}')
[ -n "$ids" ] && docker rm $ids
```

**Never, unless you mean to lose app data:**
```bash
docker volume prune -a                 # can delete smartintern_v2_appdata
docker system prune --volumes
docker compose down -v
wsl --unregister docker-desktop        # wipes Docker entirely
```
Back up a volume first if in doubt (A5).

Cost of pruning: the next `docker compose up --build` of each project is slower once
(the cache rebuilds). Nothing else.

## A3. Give the space back to Windows: TRIM + compact

Do this after A2. Takes ~5 minutes. Needs **one admin (UAC) prompt**. Safe: nothing is
deleted; the disk is opened read-only.

**Step 1: TRIM** (Docker running). Tells the virtual disk which blocks are free. *Without
this, compaction barely helps* (we got 26.7 → 20.7 GB without it, 20.7 → 9.9 GB with it).
```bash
MSYS_NO_PATHCONV=1 docker run --rm --privileged --pid=host python:3.13-slim \
  nsenter -t 1 -m -- fstrim -av
```
(Any small image works in place of `python:3.13-slim`.)

**Step 2: stop Docker and WSL** (PowerShell):
```powershell
Get-Process "Docker Desktop","com.docker.backend","com.docker.build" -ErrorAction SilentlyContinue |
  Stop-Process -Force -Confirm:$false
wsl --shutdown
wsl -l -v          # docker-desktop must say Stopped
```

**Step 3: compact with diskpart, as admin.** Save this as `compact.txt` (replace `<you>`):
```
select vdisk file="C:\Users\<you>\AppData\Local\Docker\wsl\disk\docker_data.vhdx"
attach vdisk readonly
compact vdisk
detach vdisk
```
Then run (accept the UAC prompt; it may hide behind other windows on the taskbar):
```powershell
Start-Process powershell -Verb RunAs -Wait -ArgumentList "-NoProfile -Command `"diskpart /s 'C:\path\to\compact.txt' *> 'C:\path\to\compact.log'`""
Get-Content C:\path\to\compact.log | Select-String "successfully|error"
"docker_data.vhdx {0:N2} GB" -f ((Get-Item "$env:LOCALAPPDATA\Docker\wsl\disk\docker_data.vhdx").Length/1GB)
```
Expect four "DiskPart successfully …" lines. (`Optimize-VHD` doesn't exist on Windows Home;
diskpart is the way.) If the log says "The operation was canceled by the user", the UAC
prompt was declined/closed: run it again.

**Step 4: start Docker Desktop** and check nothing is missing:
```bash
docker system df
docker ps -a --format '{{.Names}}'
docker volume ls -q
```

## A4. Keep it from happening again

- **There is no working disk limit on the WSL 2 backend** (`DiskSizeMiB` is ignored, see B7).
  The disk can grow to 1 TB, so the habits below are what keep it in check.
- **If the file carries lots of overhead** (vhdx far bigger than `df` inside the VM even
  after A3), the only full fix is a fresh disk: back up volumes (A5) → **Troubleshoot →
  Clean / Purge data → WSL 2** → restore (A5) → rebuild. That removed ~5.4 GB of overhead.
- **Prune the build cache** whenever `docker system df` shows it at several GB. It's the
  thing that grows with every `--build`.
- **Remove finished projects** (`docker compose down` in that project + `docker image rm`).
- **Every few months, or when C: is low:** A1 → A2 → A3.
- Don't move the disk to D: (slower drive; builds need the SSD).

## A4b. What to expect day to day (after the first build)

The **first build from scratch** is the big one: it filled the fresh disk to 12 GB for
~4 GB kept (B8). After that the file should **stay around that size**:

- **Code-only changes rebuild only the last step.** Earlier steps (base image, `pip install`,
  `npm install`) come from the build cache; only the "copy your code" step reruns, a few MB to
  a few hundred MB.
- **Builds reuse the free space inside the file.** The file already has ~8 GB of empty room
  from the first build. Docker fills that before the file grows. It grows past its current
  size only when Docker's total content exceeds it.

What slowly accumulates (inside the file, and only grows it once the free room is used up):

| What | Why | Size |
| --- | --- | --- |
| Old image versions (`<none>` tag) | every `--build` leaves the previous image behind | a few hundred MB per rebuild |
| Build cache from dependency changes | editing `requirements.txt` / `package.json` reruns the whole install step; the old version stays cached | hundreds of MB to ~1 GB per change |

Housekeeping:
```bash
docker system df                 # glance occasionally
docker image prune -f            # drop old <none> images when they pile up
docker builder prune -a -f       # when Build Cache reaches several GB (next build is slower once)
```
These free space **inside** the file (room for future builds). They don't shrink the file
on C:; that needs A3. **No need to compact after every build.** Only when C: runs low:
A1 → A2 → A3.

Best order when building several projects: build them all first, **then** compact once
(each first build temporarily grows the file).

## A5. Back up / restore a volume

App data in volumes **can't** be rebuilt from code. Back up before any reset or purge.
Stop the app first (`docker compose stop`) so SQLite / Milvus files are consistent.

```bash
# Backup → data_warehouse/backups/ (gitignored)
mkdir -p /d/Work/Agents/SmartIntern_v2/data_warehouse/backups
docker run --rm -v smartintern_v2_appdata:/data:ro \
  -v "D:/Work/Agents/SmartIntern_v2/data_warehouse/backups:/backup" \
  python:3.13-slim sh -c 'tar czf /backup/smartintern_v2_appdata.tgz -C /data . && tar tzvf /backup/smartintern_v2_appdata.tgz'

# Restore
docker volume create smartintern_v2_appdata
docker run --rm -v smartintern_v2_appdata:/data \
  -v "D:/Work/Agents/SmartIntern_v2/data_warehouse/backups:/backup:ro" \
  python:3.13-slim sh -c 'cd /data && tar xzf /backup/smartintern_v2_appdata.tgz && ls -la /data'
```
The volume holds `app.db` (+ `-wal`/`-shm`), `milvus.db/` (memory-card vectors) and
`files/resumes/` (uploaded files). `data_warehouse/snapshots/app.db` only has the DB tables.
Compose may warn that a manually created volume "was not created by Docker Compose". That's harmless.

## A6. Changing the disk limit (doesn't work on WSL 2: kept for reference)

> Tried 2026-11-17: Docker Desktop 4.99 on WSL 2 ignored `DiskSizeMiB`, even on a freshly
> created disk (B7). The steps below are useful only as **the fresh-disk procedure** (back up →
> purge → restore → rebuild), which removes accumulated overhead.

1. Back up volumes (A5).
2. Quit Docker Desktop (tray → Quit), then `wsl --shutdown`.
3. Edit the setting (there's no slider on the WSL 2 backend, see B7):
   ```powershell
   $f = "$env:APPDATA\Docker\settings-store.json"
   Copy-Item $f "$f.bak" -Force
   $j = Get-Content $f -Raw | ConvertFrom-Json
   $j | Add-Member -NotePropertyName DiskSizeMiB -NotePropertyValue 25600 -Force   # GB × 1024
   [IO.File]::WriteAllText($f, ($j | ConvertTo-Json -Depth 20))
   ```
4. Start Docker Desktop. The existing disk **keeps its old size**, so recreate it:
   **Troubleshoot (bug icon, top right) → Clean / Purge data → tick WSL 2 → Delete.**
5. Verify: `MSYS_NO_PATHCONV=1 docker run --rm --privileged --pid=host python:3.13-slim nsenter -t 1 -m -- df -h /mnt/docker-desktop-disk` → Size ≈ the new limit.
6. Restore volumes (A5), then `docker compose up --build -d` in each project and check
   `http://localhost:3000/api/health` → `"status": "ok"`.

## A7. Windows shell gotchas

- Docker `--format '{{.Label "x"}}'` templates break in PowerShell quoting. Use Git Bash.
- Git Bash rewrites Linux paths in arguments (`/mnt/x` → `C:/Program Files/Git/mnt/x`).
  Prefix the command with `MSYS_NO_PATHCONV=1`.
- Nested quotes in `python -c "..."` break in PowerShell. Write a script file instead.
- `diskpart` needs an elevated shell. A declined UAC prompt only shows
  "The operation was canceled by the user".
- If `docker` hangs or returns `500 Internal Server Error ... dockerDesktopLinuxEngine`, the
  engine isn't up (often: C: full). Fix space first, then restart Docker Desktop.

---

# PART B: RECORD OF THE 2026-11-17 SESSION

## B1. Symptoms

- Docker Desktop wouldn't start; `docker system df` returned
  `request returned 500 Internal Server Error for API route ... dockerDesktopLinuxEngine ...`.
- A treemap tool showed ~25.3 GB under "WSL data / Docker".
- **C: had 0.3 GB free** (D: had 77 GB).

## B2. How Docker stores data on Windows

| Thing | What it is |
| --- | --- |
| **WSL 2** | Windows' Linux VM layer. **Docker Desktop runs on it.** On Windows 11 Home (no Hyper-V) it's the only backend, so WSL is required. |
| `docker-desktop` distro | Docker's engine VM (`%LOCALAPPDATA%\Docker\wsl\main\ext4.vhdx`, ~0.1 GB). Never unregister it. |
| `docker_data.vhdx` | `%LOCALAPPDATA%\Docker\wsl\disk\`: everything Docker stores. |
| `Ubuntu` distro | Separate, optional Linux install (13.7 GB). Not used by Docker or SmartIntern. The user removed it. |

`docker_data.vhdx` is a dynamic, **non-sparse** VHDX (`fsutil sparse queryflag` →
"NOT set as sparse"), so Windows can't release freed space on its own. Its size is the
**high-water mark**. Stopped containers, old images, cache and volumes all count, running or not.

## B3. What we found

| | Size |
| --- | --- |
| C: free | 0.3 GB |
| `docker_data.vhdx` | 25.3 GB |
| Ubuntu WSL disk | 13.7 GB |
| `%TEMP%` | 1.3 GB |

| `docker system df` | Total | Size | Reclaimable |
| --- | --- | --- | --- |
| Images | 26 (≈10 projects) | 7.05 GB | |
| Containers | 21, all stopped | 6 MB | 100 % |
| Volumes | 4 | 52 MB | |
| **Build cache** | 367 | **10.33 GB** | 6.5 GB |

Why so big: images from ~10 old projects (nexa, voice-agent 1.26 GB backend, astrobase,
quantumloopai, app, nudgeinstitute, splitwise-mcp, slashdocs + postgres/dex/versitygw,
aeris, SmartIntern), build cache from every `--build` (pip/npm layers with heavy packages:
milvus-lite, pymupdf, openai), old image versions from rebuilds, plus logs/metadata/temp
build space not shown by `docker system df`.

## B4. What we did

1. User freed C: and ran `wsl --unregister Ubuntu`.
2. Removed 17 containers, keeping aeris + smartintern_v2 (A2 command).
3. Removed 21 images, keeping `aeris-*`, `smartintern_v2-*`, `python:3.13-slim` → 26 → 5 images, 7.05 → 1.68 GB.
4. `docker builder prune -a -f` → freed 10.33 GB.
5. User chose to delete volumes `nudgeinstitute_app-data`, `slashdocs_blob-data`,
   `slashdocs_postgres-data` (data gone for good). *Side effect:* slashdocs was also an MCP
   server in Claude Code; it can't connect until set up again.
6. Result: ~1.7 GB used inside Docker, but `docker_data.vhdx` had **grown** to 26.75 GB,
   and C: free fell from ~13 GB to ~11.6 GB (deletion bookkeeping written to fresh space).
7. Compaction without TRIM: 26.7 → **20.7 GB** (Linux hadn't marked freed blocks).
8. `fstrim -av` inside the VM, then compaction again: 20.7 → **9.9 GB**. (One UAC prompt was
   cancelled on the way; retried.)
9. Verified after restart: same 5 images, 4 containers, volumes intact.

| | Start | After prune | After compaction |
| --- | --- | --- | --- |
| `docker_data.vhdx` | 25.3 GB | 26.75 GB | **9.9 GB** |
| C: free | 0.3 GB | 11.6 GB | **28.4 GB** |

Compaction side effects: none to data. The file grows again as Docker needs space.

## B5. What was still in the 9.9 GB

`df` inside the VM: **4.5 GB used** on a **1007 GB** filesystem.

| Part | Size | Notes |
| --- | --- | --- |
| `data/desktop-containerd` (5 images) | 3.1 GB | Stored twice: compressed + unpacked (so more than `docker system df`'s 1.7 GB). Rebuildable. |
| `isocache` | 1.4 GB | Docker Desktop's own system image. Not removable. |
| volumes, containers, buildkit, network | ~65 MB | |
| **Overhead** | **~5.4 GB** | Journal (≤ ~1 GB, crash safety: needed), inode tables/bitmaps sized for a **1 TB** disk (mostly describing empty space), partly-used multi-MB VHDX blocks compaction can't drop (waste). Estimated split. |

## B6. Deciding the disk limit

Docker Desktop's default limit is **1 TB** (no `DiskSizeMiB` key in `settings-store.json`),
far bigger than the 256 GB SSD, and the overhead scales with it. The limit is a **cap, not a
reservation**.

| | Size |
| --- | --- |
| Docker system cache | 1.4 GB |
| SmartIntern + aeris images (×2 storage) | ~3 GB |
| Build cache after many rebuilds | up to ~10 GB |
| App data | < 1 MB |
| **Realistic peak** | **~15 GB** |

- 15 GB: too tight. A rebuild briefly holds old + new images, so builds would often fail.
- **25 GB: chosen.** ~10 GB headroom, small overhead, caps Docker at ~10 % of the SSD.
- 32 GB: also fine.
- Kept on C: for build speed (D: rejected).
- Changing the limit later = another wipe/restore cycle, so don't go too small.

## B7. Setting the limit: what we learned

- On the WSL 2 backend, **Settings → Resources → Advanced has no disk slider.** It only
  says: *"You are using the WSL 2 backend, so resource limits are managed by Windows. You can
  configure limits on the memory, CPU, and swap size allocated to WSL 2 in a .wslconfig file."*
- `.wslconfig` does **not** control Docker's data disk (only WSL memory/CPU/swap).
- The real setting is **`DiskSizeMiB`** in `%APPDATA%\Docker\settings-store.json` (name
  confirmed inside `com.docker.backend.exe`). Set to `25600`; original saved as
  `settings-store.json.bak`. It persists across restarts.
- **An existing disk keeps its size** (still `1007G` after restart).
- **Troubleshoot → Clean / Purge data → WSL 2 does NOT recreate the disk.** It empties it
  (all images/containers/volumes gone) and the file shrank to 1.64 GB, but it was the same
  file (creation date unchanged) and still `1007G`.
- We then quit Docker, moved the empty `docker_data.vhdx` aside and let Docker create a
  brand-new one. **Still `1007G`.** Conclusion: **on the WSL 2 backend Docker Desktop 4.99
  ignores `DiskSizeMiB`; the disk limit can't be lowered.** (The key is left in
  `settings-store.json`; it's harmless. `settings-store.json.bak` is the original.)
- **What actually mattered:** the fresh disk had **no ~5.4 GB overhead** (1.45 GB file for
  1.6 GB used). The overhead came from the old disk's history (fragmentation, scattered
  metadata from years of grow/delete), not from the 1 TB size. So the purge achieved the goal anyway.

## B8. Outcome

- [x] SmartIntern volume backed up: `data_warehouse/backups/smartintern_v2_appdata.tgz` (425 KB)
- [x] `DiskSizeMiB = 25600` set (no effect on WSL 2, see B7)
- [x] Purge (Troubleshoot → Clean / Purge data → WSL 2)
- [x] Restored `smartintern_v2_appdata`, rebuilt SmartIntern: health `ok`; Desk shows
      1 resume parsed, profile confirmed, 17 memory cards all embedded, Milvus loaded
- [ ] Rebuild aeris (`docker compose up --build` in its folder)
- [x] Backup `.tgz` deleted after the restore was verified (make a fresh one with A5 before any future purge)

| | Start of session | After compaction | After purge (empty) | After SmartIntern rebuild |
| --- | --- | --- | --- | --- |
| `docker_data.vhdx` | 25.3 GB | 9.9 GB | 1.45 GB | **12.0 GB** |
| C: free | 0.3 GB | 28.4 GB | 36.5 GB | **26.1 GB** |

**Why one build grew the file to 12 GB** while `docker system df` shows ~4 GB (2.0 GB
images + 2.0 GB build cache): a build temporarily writes much more than it keeps (pip
downloads, unpacking layers, the compressed + unpacked copy of each image, intermediate
layers). The file keeps that peak. It's a **one-time high-water mark**: later builds reuse
the same space inside the file, so it should stay around this size. If you want those GB
back on C: anyway, run A3 (TRIM + compact). It should land near ~5 GB but will regrow on the
next big build.
