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
