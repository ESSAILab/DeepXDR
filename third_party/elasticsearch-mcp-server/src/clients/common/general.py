from typing import Dict, Optional

from src.clients.base import SearchClientBase

class GeneralClient(SearchClientBase):
    def general_api_request(self, method: str, path: str, params: Optional[Dict] = None, body: Optional[Dict] = None):
        """Perform a general HTTP API request.
           Use this tool for any Elasticsearch/OpenSearch API that does not have a dedicated tool.
        """
        return self.general_client.request(method, path, params, body)
