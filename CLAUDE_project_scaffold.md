# CLAUDE.md

Guidance for Claude Code when working in this repository.

This file is a **blank-canvas starter**. It assumes nothing about what the project is.
It fixes only the languages (Python backend, Node.js + TypeScript frontend), a few seams
that keep a project easy to change, and a boilerplate that runs in Docker on day one.
Everything else is a default. Override it as the project's real needs become clear.

---

## 0. Using this template

1. Copy this file into an empty repo **at the root**, named `CLAUDE.md`. Claude Code only
   auto-loads it from the root (or `.claude/CLAUDE.md`), not from a subfolder.
2. Ask Claude to **"scaffold the project"**. Claude creates every file in **Appendix A**
   exactly as written (the appendix is the source of truth, not a sketch), creates the
   empty files listed there, and copies `.env.example` to `.env` and
   `mcp-server/.env.example` to `mcp-server/.env`.
3. Run `docker compose up --build`, open <http://localhost:3000> and click
   **Check connection**. Expected result:
   - ✅ Frontend is serving this page
   - ✅ Backend reachable
   - ⚠️ LLM not configured yet (until `LLM_*` is filled in `.env`)
4. Fill in **§1**, delete any piece the project doesn't need (see §3), then **delete
   Appendix A** from this file. It has done its job, and keeping it costs context in
   every session.

---

## 1. This project

_Blank in the template. Fill in once the idea is clear; keep it short._

- **What it is:**
- **Decisions made so far** (database, frameworks, model provider, deploy target):
- **Things Claude should know** (domain terms, constraints, people):

---

## 2. Working rules for Claude

- **Keep the setup check green.** After changing the backend, frontend, Dockerfiles or
  `docker-compose.yml`, `docker compose up --build` must still come up healthy and
  `GET /api/health` (through the frontend) must still return `"status": "ok"`.
- **Ask before adding** a dependency, a Compose service, a framework or a database.
  When one is added, add it to the manifest (`requirements.txt`, `package.json`) and
  the Dockerfile in the same change; remove it when it stops being used.
- **Never read, print or commit `.env` values.** When a new setting is needed, add the
  key to `.env.example` (with a safe default or blank) in the same change.
- **Don't commit or push unless asked.**
- **Respect the seams** in §5 and §6 and the import direction in §7. If a change seems
  to need breaking one, stop and say so instead.
- **Prefer the simple version.** No multi-agent framework, vector DB, queue or frontend
  framework until the simple version has actually run out of room.

---

## 3. Directory layout

```
<project-root>/
├── CLAUDE.md                 # This file. Must be at the root to be loaded.
├── .claude/                  # Claude Code config: settings.json, hooks, skills
├── backend/                  # API layer, the single source of truth for logic
│   ├── main.py               # Entrypoint, wiring only: app, routes, error handlers
│   ├── config.py             # The ONLY module that reads env vars
│   ├── model.py              # The ONLY place a model client is constructed (§5)
│   ├── agents/               # Agent / orchestration logic (calls model.py)
│   └── Dockerfile
├── frontend/                 # Node.js + TypeScript; framework inside is open
│   ├── src/server.ts         # Serves public/ and proxies /api/* to the backend
│   ├── public/index.html     # Setup-check page; replace when the real UI starts
│   ├── package.json
│   ├── tsconfig.json
│   └── Dockerfile
├── mcp-server/               # Optional thin pathway INTO the backend (§6)
│   ├── src/config.py         # Layer 0: how to reach the backend, nothing else
│   ├── src/tools.py          # Layer 1: each tool = one backend HTTP call
│   ├── src/server.py         # Layer 2: FastMCP instance + transport
│   ├── requirements.txt
│   └── .env / .env.example
├── data_warehouse/           # Datasets, seed data, exports (contents gitignored)
├── experiments/              # Notebooks, prototypes, throwaway scripts
├── MD_files/                 # Idea docs, design notes, generated artifacts
├── docker-compose.yml        # backend + frontend; add services only once they're real
├── requirements.txt          # Backend Python deps
├── .env / .env.example       # Root config for backend + frontend
├── .gitignore / .dockerignore
└── README.md
```

Empty folders keep a `.gitkeep`. Delete what the project genuinely doesn't need (no
agent tool-calling? delete `mcp-server/`) instead of leaving hollow placeholders.

---

## 4. Stack: fixed languages, open frameworks

| Layer | Default | Swap freely for |
| --- | --- | --- |
| Backend | **Python**, FastAPI + Uvicorn | The framework only. Python is fixed. |
| Frontend | **Node.js + TypeScript**, plain `node:http` server + static page | Vite/React, Next.js, etc. Node + TS is fixed. |
| Agent/LLM | `backend/agents/` calling `backend/model.py` | Any orchestration approach (the §5 rule still applies) |
| MCP server | `fastmcp` (standalone package), only if an agent needs to call in | — |
| Database | None until there's real state to persist | SQLite/DuckDB to start, Postgres if it grows |
| Packaging | `docker-compose.yml`: `backend` + `frontend` | Add services as they become real |

No versions are pinned. Docker images track `python:3-slim` and `node:lts-alpine`, and
packages resolve to latest stable at install time. Pin only when reproducibility
actually needs it.

---

## 5. The one rule that matters most: model/provider choice is config, not code

The project may call a hosted API, a local model, or several. Whatever it is, **build
model clients in exactly one module (`backend/model.py`)** and have everything else call
`get_client()`, never a provider SDK directly.

```
LLM_PROVIDER=<anthropic | openai | ollama | ...>
LLM_MODEL=<provider's model id>
LLM_API_KEY=<key, or blank for a local/keyless endpoint>
LLM_BASE_URL=<optional: any OpenAI-compatible endpoint>
```

- Swapping models or providers is an `.env` edit, not a code change.
- The provider SDK is **not** in `requirements.txt` by default. Add the one you choose.
  Until then `/health` reports exactly what's missing.
- A missing key or package raises `ModelConfigError` with a message naming the fix;
  `main.py` turns it into a `503` with that message, never an opaque `500`.
- A framework (LangChain, LangGraph, an agent SDK, or plain SDK calls) is a separate
  choice. The rule is only: one seam, no model names scattered across call sites.
- Inside Docker, `localhost` is the container. To reach a model server on the host
  (e.g. Ollama), set `LLM_BASE_URL=http://host.docker.internal:11434/v1`.

---

## 6. The MCP server is a pathway, not a second backend

```
agent (MCP client) ──MCP──▶ mcp-server/src/tools.py ──HTTP──▶ backend API ──▶ db / model
```

- **Every tool is a thin wrapper:** take the arguments, call the backend's HTTP API,
  return the result. No business logic, database access or model calls in the MCP
  server. If REST and MCP need the same behavior, it lives once in `backend/`.
- Type hints and docstrings on each tool are the schema the agent sees. Write them for
  that reader.
- **Its own `.env` and `src/config.py`**, separate from the root. Only how to reach the
  backend and how to serve MCP. No `LLM_*` keys.
- **Errors are translated, not leaked:** tools raise `ToolError` with the backend's
  `detail`, or a "backend unreachable at …, start it with …" message.
- **Use `fastmcp`**, imported as `from fastmcp import FastMCP`. Not
  `mcp.server.fastmcp`, which is the low-level SDK's path and has changed between
  versions. `host`/`port` go to `mcp.run()`, not the constructor; `stdio` takes neither.
- Not in Docker Compose by default: an MCP client usually launches it over `stdio`.

---

## 7. Conventions

- **`backend/main.py` is wiring only.** Logic lives in `model.py`, `agents/` or wherever
  it naturally belongs.
- **Import direction is a rule.** `config` ← `model` ← `main` in `backend/`;
  `config` ← `tools` ← `server` in `mcp-server/src/`. `tools.py` exports plain functions
  plus a `TOOLS` list, and only `server.py` touches the FastMCP object
  (`mcp.add_tool(fn)`). If two modules want each other, the shared thing belongs lower.
- **The browser only talks to the frontend server.** `frontend/src/server.ts` proxies
  `/api/*` to `BACKEND_URL` (`/api/health` → `/health`). No CORS, and the same code works
  locally (`http://localhost:8000`) and in Compose (`http://backend:8000`, set in
  `docker-compose.yml`).
- **Two `.env` files, two owners.** Root `.env` = backend + frontend. `mcp-server/.env` =
  MCP only. Both gitignored, both with a committed `.example`. Compose loads the root
  `.env` if it exists (`required: false`), so `docker compose up` works without one.
- **No inline comments in `.env` files.** Compose's `env_file` keeps a trailing `# ...`
  as part of the value. Comments go on their own line.
- **Optional subsystems are imported inside the function that needs them**, so the app
  still boots when one isn't installed or configured yet.
- **`frontend/tsconfig.json` lists `"types": ["node"]`.** Recent TypeScript versions no
  longer pick up `@types/node` automatically, and `tsc` fails on `node:*` imports
  without it.
- Keep manifests flat and honest: add a dependency when you use it, remove it when you
  stop.

---

## 8. Deliberately left open

Decide these when the project's shape is clear, and record the decision in §1:

- Agent orchestration approach
- Backend framework (FastAPI by default)
- Database (none until needed)
- Frontend framework (a static page is a legitimate UI)
- Version pins (none until reproducibility needs them)
- Testing, CI, linting (add when the project warrants it)

---

## 9. Commands

```bash
# Docker (default)
cp .env.example .env
docker compose up --build            # http://localhost:3000 → "Check connection"
docker compose down

# Local, without Docker
python -m venv .venv
source .venv/Scripts/activate        # Windows Git Bash  (macOS/Linux: .venv/bin/activate)
pip install -r requirements.txt
uvicorn backend.main:app --reload --port 8000
cd frontend && npm install && npm run dev

# MCP server (only if used; needs the backend up)
pip install -r mcp-server/requirements.txt
cd mcp-server && python src/server.py
```

```powershell
python -m venv .venv; .venv\Scripts\Activate.ps1
```

---

## Appendix A: Boilerplate files (delete this appendix after scaffolding)

Create each file below **exactly** as written. Then create these empty files:
`backend/__init__.py`, `backend/agents/__init__.py`, `data_warehouse/.gitkeep`,
`experiments/.gitkeep`, `MD_files/.gitkeep`, and the folder `.claude/`.
Finally copy `.env.example` → `.env` and `mcp-server/.env.example` → `mcp-server/.env`.

> Never use PowerShell `New-Item -Force` on an existing **file**: it truncates it.


### `docker-compose.yml`

```yaml
services:
  backend:
    build:
      context: .
      dockerfile: backend/Dockerfile
    env_file:
      - path: .env
        required: false
    ports:
      - "${BACKEND_PORT:-8000}:8000"
    healthcheck:
      test: ["CMD", "python", "-c", "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')"]
      interval: 5s
      timeout: 3s
      retries: 12

  frontend:
    build: ./frontend
    env_file:
      - path: .env
        required: false
    environment:
      BACKEND_URL: http://backend:8000
      FRONTEND_PORT: "3000"
    ports:
      - "${FRONTEND_PORT:-3000}:3000"
    depends_on:
      backend:
        condition: service_healthy
```

### `.env.example`

```bash
# Copy to .env. Never put a comment on the same line as a value.
APP_NAME=app

# LLM — read only by backend/config.py
LLM_PROVIDER=
LLM_MODEL=
LLM_API_KEY=
LLM_BASE_URL=

# Host ports (docker compose and local runs)
BACKEND_PORT=8000
FRONTEND_PORT=3000

# Where the frontend server finds the backend on local runs. Compose overrides it.
BACKEND_URL=http://localhost:8000
```

### `.gitignore`

```gitignore
# secrets
.env
**/.env

# python
__pycache__/
*.pyc
.venv/
*-venv/

# node
node_modules/
dist/

# bulk data
data_warehouse/*
!data_warehouse/.gitkeep

# os / editors
.DS_Store
Thumbs.db
.vscode/
.idea/
```

### `.dockerignore`

```gitignore
.git
.env
**/.env
.venv
*-venv
**/__pycache__
**/node_modules
frontend
mcp-server
MD_files
data_warehouse
experiments
```

### `requirements.txt`

```text
# backend only — mcp-server has its own requirements.txt
fastapi
uvicorn[standard]
pydantic-settings
```

### `backend/config.py`

```python
"""Settings loaded from the environment / root .env. The ONLY module that reads env vars."""
from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=ROOT / ".env", extra="ignore")

    app_name: str = "app"
    llm_provider: str = ""
    llm_model: str = ""
    llm_api_key: str = ""
    llm_base_url: str = ""


@lru_cache
def get_settings() -> Settings:
    return Settings()
```

### `backend/model.py`

```python
"""THE ONLY place a model client gets constructed. Everything else calls get_client()."""
from functools import lru_cache

from backend.config import get_settings

OLLAMA_DEFAULT_URL = "http://localhost:11434/v1"


class ModelConfigError(RuntimeError):
    """LLM_* settings or the provider's package are missing. The message says how to fix it."""


@lru_cache
def get_client():
    s = get_settings()
    provider = s.llm_provider.strip().lower()
    if not provider:
        raise ModelConfigError("LLM_PROVIDER is not set. Add it to the root .env (see .env.example).")
    if not s.llm_model:
        raise ModelConfigError("LLM_MODEL is not set. Add the provider's model id to the root .env.")

    if provider == "anthropic":
        if not s.llm_api_key:
            raise ModelConfigError("LLM_API_KEY is not set for provider 'anthropic'.")
        try:
            from anthropic import Anthropic
        except ImportError as e:
            raise ModelConfigError("Package 'anthropic' missing. Add it to requirements.txt and reinstall.") from e
        return Anthropic(api_key=s.llm_api_key, base_url=s.llm_base_url or None)

    if provider in ("openai", "ollama") or s.llm_base_url:
        base_url = s.llm_base_url or (OLLAMA_DEFAULT_URL if provider == "ollama" else None)
        if not s.llm_api_key and base_url is None:
            raise ModelConfigError(f"LLM_API_KEY is not set for provider '{provider}'.")
        try:
            from openai import OpenAI
        except ImportError as e:
            raise ModelConfigError("Package 'openai' missing. Add it to requirements.txt and reinstall.") from e
        return OpenAI(api_key=s.llm_api_key or "none", base_url=base_url)

    raise ModelConfigError(f"Unsupported LLM_PROVIDER '{s.llm_provider}'. Add a branch for it in backend/model.py.")


def llm_status() -> dict:
    """Validate LLM config without a network call. Used by /health."""
    s = get_settings()
    try:
        get_client()
    except ModelConfigError as e:
        return {"configured": False, "detail": str(e)}
    return {"configured": True, "provider": s.llm_provider, "model": s.llm_model}
```

### `backend/main.py`

```python
"""Entrypoint — wiring only: app, routes, error handlers, startup/shutdown."""
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from backend.config import get_settings
from backend.model import ModelConfigError, llm_status

app = FastAPI(title=get_settings().app_name)


@app.exception_handler(ModelConfigError)
def model_config_error(_: Request, exc: ModelConfigError) -> JSONResponse:
    return JSONResponse(status_code=503, content={"detail": str(exc)})


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "app": get_settings().app_name, "llm": llm_status()}
```

### `backend/Dockerfile`

```dockerfile
FROM python:3-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY backend ./backend
EXPOSE 8000
CMD ["uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

### `frontend/package.json`

```json
{
  "name": "frontend",
  "private": true,
  "type": "module",
  "scripts": {
    "dev": "tsx watch src/server.ts",
    "build": "tsc",
    "start": "node dist/server.js"
  },
  "devDependencies": {
    "@types/node": "latest",
    "tsx": "latest",
    "typescript": "latest"
  }
}
```

### `frontend/tsconfig.json`

```json
{
  "compilerOptions": {
    "target": "ES2022",
    "module": "NodeNext",
    "moduleResolution": "NodeNext",
    "outDir": "dist",
    "rootDir": "src",
    "types": ["node"],
    "strict": true,
    "skipLibCheck": true
  },
  "include": ["src"]
}
```

### `frontend/src/server.ts`

```ts
// Serves public/ and proxies /api/* to the backend, so the browser never needs CORS
// and BACKEND_URL works the same locally and inside Docker.
import { createServer } from "node:http";
import { readFile } from "node:fs/promises";
import { extname, join, normalize } from "node:path";
import { fileURLToPath } from "node:url";

try {
  process.loadEnvFile("../.env"); // local runs from frontend/; absent in Docker, which is fine
} catch {}

const PORT = Number(process.env.FRONTEND_PORT ?? 3000);
const BACKEND_URL = (process.env.BACKEND_URL ?? "http://localhost:8000").replace(/\/$/, "");
const PUBLIC_DIR = fileURLToPath(new URL("../public/", import.meta.url));
const TYPES: Record<string, string> = {
  ".html": "text/html; charset=utf-8",
  ".js": "text/javascript",
  ".css": "text/css",
  ".svg": "image/svg+xml",
  ".png": "image/png",
};

createServer(async (req, res) => {
  const url = new URL(req.url ?? "/", "http://localhost");

  if (url.pathname.startsWith("/api/")) {
    const chunks: Buffer[] = [];
    for await (const chunk of req) chunks.push(chunk);
    const hasBody = !["GET", "HEAD"].includes(req.method ?? "GET");
    try {
      const upstream = await fetch(BACKEND_URL + url.pathname.slice(4) + url.search, {
        method: req.method,
        headers: { "content-type": req.headers["content-type"] ?? "application/json" },
        body: hasBody ? new Uint8Array(Buffer.concat(chunks)) : undefined,
      });
      res.writeHead(upstream.status, {
        "content-type": upstream.headers.get("content-type") ?? "application/json",
      });
      res.end(new Uint8Array(await upstream.arrayBuffer()));
    } catch {
      res.writeHead(502, { "content-type": "application/json" });
      res.end(JSON.stringify({ detail: `Backend unreachable at ${BACKEND_URL}` }));
    }
    return;
  }

  const rel = normalize(url.pathname === "/" ? "index.html" : url.pathname).replace(/^([/\\]|\.\.)+/, "");
  try {
    const body = await readFile(join(PUBLIC_DIR, rel));
    res.writeHead(200, { "content-type": TYPES[extname(rel)] ?? "application/octet-stream" });
    res.end(body);
  } catch {
    res.writeHead(404, { "content-type": "text/plain" });
    res.end("Not found");
  }
}).listen(PORT, () => console.log(`frontend on http://localhost:${PORT} -> backend ${BACKEND_URL}`));
```

### `frontend/public/index.html`

```html
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Setup check</title>
  <style>
    :root { color-scheme: light dark; font-family: system-ui, sans-serif; }
    body { max-width: 34rem; margin: 4rem auto; padding: 0 1rem; line-height: 1.5; }
    button { font: inherit; padding: .5rem 1rem; cursor: pointer; }
    ul { list-style: none; padding: 0; }
    li { padding: .4rem 0; border-bottom: 1px solid #8884; }
    .ok::before { content: "✅ "; } .warn::before { content: "⚠️ "; } .fail::before { content: "❌ "; }
    pre { font-size: .8rem; opacity: .7; white-space: pre-wrap; }
  </style>
</head>
<body>
  <h1>Setup check</h1>
  <p>Placeholder page: it only proves the wiring works. Replace it once the project starts.</p>
  <button id="check">Check connection</button>
  <ul id="results"></ul>
  <pre id="raw"></pre>
  <script>
    const results = document.getElementById("results");
    const raw = document.getElementById("raw");
    const row = (cls, text) => {
      const li = document.createElement("li");
      li.className = cls;
      li.textContent = text;
      results.append(li);
    };
    document.getElementById("check").addEventListener("click", async () => {
      results.replaceChildren();
      raw.textContent = "";
      row("ok", "Frontend is serving this page");
      try {
        const res = await fetch("/api/health");
        const data = await res.json();
        raw.textContent = JSON.stringify(data, null, 2);
        if (!res.ok) return row("fail", `Backend: ${data.detail ?? res.status}`);
        row("ok", `Backend reachable (${data.app})`);
        data.llm.configured
          ? row("ok", `LLM configured: ${data.llm.provider} / ${data.llm.model}`)
          : row("warn", `LLM not configured yet: ${data.llm.detail}`);
      } catch (e) {
        row("fail", `Frontend server unreachable: ${e}`);
      }
    });
  </script>
</body>
</html>
```

### `frontend/Dockerfile`

```dockerfile
FROM node:lts-alpine
WORKDIR /app
COPY package.json ./
RUN npm install
COPY tsconfig.json ./
COPY src ./src
COPY public ./public
RUN npm run build
EXPOSE 3000
CMD ["node", "dist/server.js"]
```

### `frontend/.dockerignore`

```gitignore
node_modules
dist
```

### `mcp-server/requirements.txt`

```text
fastmcp
httpx
python-dotenv
```

### `mcp-server/.env.example`

```bash
MCP_SERVER_NAME=app
MCP_TRANSPORT=stdio
MCP_HOST=127.0.0.1
MCP_PORT=8765
BACKEND_URL=http://localhost:8000
REQUEST_TIMEOUT=120
```

### `mcp-server/src/config.py`

```python
"""Layer 0. Loads mcp-server/.env — how to reach the backend and serve MCP, nothing else."""
import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

MCP_SERVER_NAME = os.getenv("MCP_SERVER_NAME", "app")
MCP_TRANSPORT = os.getenv("MCP_TRANSPORT", "stdio")
MCP_HOST = os.getenv("MCP_HOST", "127.0.0.1")
MCP_PORT = int(os.getenv("MCP_PORT", "8765"))
BACKEND_URL = os.getenv("BACKEND_URL", "http://localhost:8000").rstrip("/")
REQUEST_TIMEOUT = float(os.getenv("REQUEST_TIMEOUT", "120"))
```

### `mcp-server/src/tools.py`

```python
"""Layer 1. Each tool = one call to the backend's HTTP API, nothing more."""
import httpx
from fastmcp.exceptions import ToolError

from config import BACKEND_URL, REQUEST_TIMEOUT


def _request(method: str, path: str, **kwargs):
    try:
        r = httpx.request(method, f"{BACKEND_URL}{path}", timeout=REQUEST_TIMEOUT, **kwargs)
    except httpx.ConnectError as e:
        raise ToolError(
            f"Backend unreachable at {BACKEND_URL}. Start it with: docker compose up "
            "(or: uvicorn backend.main:app --port 8000)"
        ) from e
    if r.is_error:
        try:
            detail = r.json().get("detail", r.text)
        except ValueError:
            detail = r.text
        raise ToolError(f"Backend error {r.status_code}: {detail}")
    return r.json()


def health() -> dict:
    """Check that the backend is up and whether its LLM provider is configured."""
    return _request("GET", "/health")


TOOLS = [health]
```

### `mcp-server/src/server.py`

```python
"""Layer 2. FastMCP instance + transport; the only module that touches the FastMCP object."""
from fastmcp import FastMCP

from config import MCP_HOST, MCP_PORT, MCP_SERVER_NAME, MCP_TRANSPORT
from tools import TOOLS

mcp = FastMCP(MCP_SERVER_NAME)
for fn in TOOLS:
    mcp.add_tool(fn)

if __name__ == "__main__":
    if MCP_TRANSPORT == "stdio":
        mcp.run(transport="stdio")
    else:
        mcp.run(transport=MCP_TRANSPORT, host=MCP_HOST, port=MCP_PORT)
```
