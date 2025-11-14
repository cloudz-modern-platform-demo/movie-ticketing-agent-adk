from google.adk.tools.mcp_tool.mcp_toolset import MCPToolset
from google.adk.tools.mcp_tool.mcp_toolset import StreamableHTTPConnectionParams


movie_ticketing_mcp_toolset = MCPToolset(
    connection_params=StreamableHTTPConnectionParams(
        url="http://localhost:9100/mcp",
        headers={"Accept": "text/event-stream"},
    ),
    tool_filter=[],
)
