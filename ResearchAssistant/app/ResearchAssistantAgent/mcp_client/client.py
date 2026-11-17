import os

from mcp.client.streamable_http import streamablehttp_client
from strands.tools.mcp.mcp_client import MCPClient


def get_papers_gw_mcp_client(authorization: str) -> MCPClient:
    """MCP client for the researchassistant-gw gateway, authenticated as the *caller*.

    `authorization` is the caller's own Authorization header, forwarded unchanged, so the
    gateway and its interceptor see the real user rather than a service identity.
    """
    url = os.environ["AGENTCORE_GATEWAY_RESEARCHASSISTANT_GW_URL"]
    return MCPClient(lambda: streamablehttp_client(url, headers={"Authorization": authorization}))
