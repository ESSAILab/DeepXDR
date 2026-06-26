from typing import Dict, Optional

from fastmcp import FastMCP

class GeneralTools:
    def __init__(self, search_client):
        self.search_client = search_client
    def register_tools(self, mcp: FastMCP):
        @mcp.tool()
        def general_api_request(method: str, path: str, params: Optional[Dict] = None, body: Optional[Dict] = None):
            """Perform a general HTTP API request.
               Use this tool for any Elasticsearch/OpenSearch API that does not have a dedicated tool.
            
            Args:
                method: HTTP method (GET, POST, PUT, DELETE, etc.)
                path: API endpoint path
                params: Query parameters
                body: Request body
            """
            return self.search_client.general_api_request(method, path, params, body)
