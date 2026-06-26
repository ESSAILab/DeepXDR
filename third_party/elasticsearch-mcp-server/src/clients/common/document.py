from typing import Dict, Optional, Any, Union, Sequence, Literal, Mapping
import json  # 添加JSON解析支持

from src.clients.base import SearchClientBase

class DocumentClient(SearchClientBase):
    def search_documents(
        self,
        index: Union[str, Sequence[str]],
        query: Optional[str] = None,
        body: Optional[Dict[str, Any]] = None,
        size: Optional[int] = 10,
        timestamp_field: Optional[str] = "@timestamp",
        event_category_field: Optional[str] = None,
        fetch_size: Optional[int] = 1000,
        fields: Optional[Union[Mapping[str, Any], Sequence[Mapping[str, Any]]]] = None,
        filter: Optional[Union[Mapping[str, Any], Sequence[Mapping[str, Any]]]] = None,
        allow_no_indices: Optional[bool] = None,
        case_sensitive: Optional[bool] = None,
        expand_wildcards: Optional[Union[Sequence[str], str]] = None,
        ignore_unavailable: Optional[bool] = None,
        keep_alive: Optional[Union[str, Literal[-1], Literal[0]]] = None,
        keep_on_completion: Optional[bool] = None,
        result_position: Optional[Union[Literal["head", "tail"], str]] = None,
        runtime_mappings: Optional[Mapping[str, Mapping[str, Any]]] = None,
        tiebreaker_field: Optional[str] = None,
        wait_for_completion_timeout: Optional[Union[str, Literal[-1], Literal[0]]] = None,
        error_trace: Optional[bool] = None,
        filter_path: Optional[Union[str, Sequence[str]]] = None,
        human: Optional[bool] = None,
        pretty: Optional[bool] = None
    ) -> Dict:
        """
        Search for documents using EQL (Event Query Language).

        Args:
            index: Name of the index, or list of indices string | Sequence[str]
            query: The EQL query string e.g. 'falco where priority == "Error"'
            body: Complete EQL request body alternative to query parameter
            size: Maximum number of matching events to return (default: 10)
            timestamp_field: Field containing event timestamp (default: "@timestamp")
            event_category_field: Field containg event classification e.g. "type" or "event.category"
            fetch_size: Max events to search per batch for sequences (default: 1000)
            fields: Array of dicts with format [{"field": "field_name"}, ...] > list[dict]
            filter: Query DSL filter applied before EQL processing > dict
            allow_no_indices: Whether to allow no indices > bool
            case_sensitive: Case sensitivity for EQL queries > bool
            expand_wildcards: Wildcard expansion mode > str or list[str]
            ignore_unavailable: Whether to ignore unavailable indices > bool
            keep_alive: Search context keep alive timeout > str
            keep_on_completion: Keep records after query completion > bool
            result_position: Result position "head" or "tail" > str
            runtime_mappings: Runtime field definitions > dict
            tiebreaker_field: Field for tiebreaking same timestamps > str
            wait_for_completion_timeout: Max time to wait for completion > str
            error_trace: Include error trace information > bool
            filter_path: Filter response to specific paths > str or list[str]
            human: Human readable output > bool
            pretty: Pretty print JSON response > bool

        【重要模型提示 - 避免AI调用错误】：

        1. FIELDS参数格式（AI模型常见错误）：
           ❌ 错误格式（会导致Pydantic验证失败）：
              fields=["*", "-attack_params.stack"]  # AI模型误用DSL语法
           ✅ 正确格式（必须符合dict列表）：
              fields=[{"field": "target"}, {"field": "attack_type"}, {"field": "plugin_message"}]

        2. NESTED FIELD ACCESS：
           {"field": "attack_params.query"}  # 访问嵌套对象的字段
           {"field": "alert.signature_id"}   # 多层嵌套访问

        3. INDEX PARAMETER：
           支持的类型：index="falco-alerts-*" 或 index=["index1", "index2"]

        4. EVENT CATEGORY MAPPING（关键配置）：
           云安全探针使用type字段：event_category_field="type"

           使用示例：
           search_documents(
               index="openrasp-alerts-*",
               query='openrasp where attack_type == "sql"',
               event_category_field="type",
               fields=[
                   {"field": "target"},
                   {"field": "attack_type"},
                   {"field": "attack_params.query"}  # 包含指定，不能排除stack
               ]
           )

        【响应过滤技巧 - 使用 filter_path 参数】

        filter_path 参数可以精准控制返回的字段路径，支持负号前缀排除：

        filter_path="-hits.events"  # 排除 hits.events 分支，常用于只获取统计信息
        filter_path=["hits.hits._source.target", "hits.hits._source.attack_type"]  # 只包含特定路径

        官方示例参考获取事件数量排除事件详情：
        ```python
        search_documents(
            index="openrasp-alerts-*",
            query='openrasp where attack_type == "sql"',
            event_category_field="type",
            filter_path="-hits.events",  # 排除事件详情，只返回总计数
            size=200
        )
        # 响应只包含：{"hits": {"total": {"value": 143, "relation": "eq"}}}

        【注意】fields参数只能包含指定，不能直接排除字段。
        真正排除字段需要使用query_type="dsl"配合_source过滤或客户端后处理。
        如果需要排除复杂嵌套字段如 attack_params.stack，最优方案是：
        1. 使用 filter_path 明确包含需要的字段路径
        2. 或在客户端后处理移除敏感字段
        """
        if self.engine_type != "elasticsearch":
            raise ValueError(f"EQL queries are not supported for {self.engine_type}. Only Elasticsearch supports EQL.")

        # 处理filter_path的类型转换（处理AI模型传入的字符串JSON数组）
        if filter_path is not None and isinstance(filter_path, str):
            try:
                # 如果是JSON数组格式的字符串，转换为Python列表
                if filter_path.startswith('[') and filter_path.endswith(']'):
                    filter_path = json.loads(filter_path)
                    print(f"[DEBUG] 转换filter_path JSON字符串为列表: {filter_path}")
            except json.JSONDecodeError as e:
                print(f"[WARNING] filter_path JSON解析失败: {e}，保持原值: {filter_path}")

        print(f"[DEBUG] 最终filter_path: {filter_path}")
        print(f"[DEBUG] filter_path最终类型: {type(filter_path)}")

        # Build EQL search parameters with all official parameters
        eql_kwargs = {
            "index": index
        }

        # Body parameters
        if body is not None:
            eql_kwargs["body"] = body
        else:
            # Build request body with provided query
            eql_body = {
                "query": query,
                "timestamp_field": timestamp_field
            }

            # Add parameters with non-default values to body
            if size is not None:
                eql_body["size"] = size
            if fetch_size is not None:
                eql_body["fetch_size"] = fetch_size
            if event_category_field is not None:
                eql_body["event_category_field"] = event_category_field
            if fields is not None:
                eql_body["fields"] = fields
            if filter is not None:
                eql_body["filter"] = filter
            if keep_alive is not None:
                eql_body["keep_alive"] = keep_alive
            if keep_on_completion is not None:
                eql_body["keep_on_completion"] = keep_on_completion
            if result_position is not None:
                eql_body["result_position"] = result_position
            if runtime_mappings is not None:
                eql_body["runtime_mappings"] = runtime_mappings
            if tiebreaker_field is not None:
                eql_body["tiebreaker_field"] = tiebreaker_field
            if wait_for_completion_timeout is not None:
                eql_body["wait_for_completion_timeout"] = wait_for_completion_timeout

            eql_kwargs["body"] = eql_body

        # URL-based parameters
        if allow_no_indices is not None:
            eql_kwargs["allow_no_indices"] = allow_no_indices
        if case_sensitive is not None:
            eql_kwargs["case_sensitive"] = case_sensitive
        if expand_wildcards is not None:
            eql_kwargs["expand_wildcards"] = expand_wildcards
        if ignore_unavailable is not None:
            eql_kwargs["ignore_unavailable"] = ignore_unavailable
        if error_trace is not None:
            eql_kwargs["error_trace"] = error_trace
        if filter_path is not None:
            eql_kwargs["filter_path"] = filter_path
        if human is not None:
            eql_kwargs["human"] = human
        if pretty is not None:
            eql_kwargs["pretty"] = pretty

        # Execute EQL search (Elasticsearch 7.9+)
        return self.client.eql.search(**eql_kwargs)
    
    def index_document(self, index: str, document: Dict, id: Optional[str] = None) -> Dict:
        """Creates a new document in the index."""
        # Handle parameter name differences between Elasticsearch and OpenSearch
        if self.engine_type == "elasticsearch":
            # For Elasticsearch: index(index, document, id=None, ...)
            if id is not None:
                return self.client.index(index=index, document=document, id=id)
            else:
                return self.client.index(index=index, document=document)
        else:
            # For OpenSearch: index(index, body, id=None, ...)
            if id is not None:
                return self.client.index(index=index, body=document, id=id)
            else:
                return self.client.index(index=index, body=document)
    
    def get_document(self, index: str, id: str) -> Dict:
        """Get a document by ID."""
        return self.client.get(index=index, id=id)
    
    def delete_document(self, index: str, id: str) -> Dict:
        """Removes a document from the index."""
        return self.client.delete(index=index, id=id)

    def delete_by_query(self, index: str, body: Dict) -> Dict:
        """Deletes documents matching the provided query."""
        return self.client.delete_by_query(index=index, body=body)

