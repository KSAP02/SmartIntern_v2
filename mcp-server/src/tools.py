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
