// Serves the built web app (dist/web) and proxies /api/* to the backend, so the browser
// never needs CORS and BACKEND_URL works the same locally and inside Docker.
import { createServer } from "node:http";
import { readFile } from "node:fs/promises";
import { extname, join, normalize } from "node:path";
import { fileURLToPath } from "node:url";

try {
  process.loadEnvFile("../.env"); // local runs from frontend/; absent in Docker, which is fine
} catch {}

const PORT = Number(process.env.FRONTEND_PORT ?? 3000);
const BACKEND_URL = (process.env.BACKEND_URL ?? "http://localhost:8000").replace(/\/$/, "");
const WEB_DIR = fileURLToPath(new URL("./web/", import.meta.url));
const TYPES: Record<string, string> = {
  ".html": "text/html; charset=utf-8",
  ".js": "text/javascript",
  ".css": "text/css",
  ".json": "application/json",
  ".svg": "image/svg+xml",
  ".png": "image/png",
  ".jpg": "image/jpeg",
  ".webp": "image/webp",
  ".ico": "image/x-icon",
  ".woff2": "font/woff2",
};
const PASS_HEADERS = ["content-type", "content-disposition", "content-length"];

createServer(async (req, res) => {
  const url = new URL(req.url ?? "/", "http://localhost");

  if (url.pathname.startsWith("/api/")) {
    const chunks: Buffer[] = [];
    for await (const chunk of req) chunks.push(chunk);
    const hasBody = !["GET", "HEAD"].includes(req.method ?? "GET");
    const headers: Record<string, string> = {};
    if (req.headers["content-type"]) headers["content-type"] = req.headers["content-type"];
    try {
      const upstream = await fetch(BACKEND_URL + url.pathname.slice(4) + url.search, {
        method: req.method,
        headers,
        body: hasBody ? new Uint8Array(Buffer.concat(chunks)) : undefined,
      });
      const body = new Uint8Array(await upstream.arrayBuffer());
      const out: Record<string, string> = {};
      for (const h of PASS_HEADERS) {
        const v = upstream.headers.get(h);
        if (v) out[h] = v;
      }
      out["content-length"] = String(body.byteLength); // fetch may have decompressed the body
      res.writeHead(upstream.status, out);
      res.end(body);
    } catch {
      res.writeHead(502, { "content-type": "application/json" });
      res.end(JSON.stringify({ detail: `Backend unreachable at ${BACKEND_URL}` }));
    }
    return;
  }

  const rel = normalize(url.pathname === "/" ? "index.html" : decodeURIComponent(url.pathname)).replace(
    /^([/\\]|\.\.)+/,
    "",
  );
  try {
    const body = await readFile(join(WEB_DIR, rel));
    const ext = extname(rel);
    const cache = rel.startsWith("assets") ? "public, max-age=31536000, immutable" : "no-cache";
    res.writeHead(200, { "content-type": TYPES[ext] ?? "application/octet-stream", "cache-control": cache });
    res.end(body);
  } catch {
    if (!extname(rel)) {
      // Client-side route (e.g. /vault): hand back the app shell.
      try {
        const html = await readFile(join(WEB_DIR, "index.html"));
        res.writeHead(200, { "content-type": TYPES[".html"], "cache-control": "no-cache" });
        res.end(html);
        return;
      } catch {}
    }
    res.writeHead(404, { "content-type": "text/plain" });
    res.end("Not found");
  }
}).listen(PORT, () => console.log(`frontend on http://localhost:${PORT} -> backend ${BACKEND_URL}`));
