from typing import Dict, Optional, Union, Any, Sequence, Mapping, Literal
import os

from fastmcp import FastMCP
from src.utils.field_truncate import apply_field_truncation

class DocumentTools:
    def __init__(self, search_client):
        self.search_client = search_client
    
    def register_tools(self, mcp: FastMCP):
        @mcp.tool()
        def search_documents(
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
                index: Name of the index, or list of indices if multiple index > string | list[string]
                query: The EQL query string (e.g., 'falco where priority == "Error"')
                body: Optional,Complete EQL query body (alternative to query parameter)
                size: Maximum number of events to fetch for basic queries (default: 10)
                timestamp_field: Field containing event timestamp (default: "@timestamp")
                event_category_field: Field containing the event classification (e.g., process, file, network)
                fetch_size: Maximum number of events to search at a time for sequence queries (default: 1000)
                fields: Array of field specifications to return, each element must be a dict with "field" key, e.g. [<{"field": "field_name"}, {"field": "nested.field"}>]
                filter: Query in Query DSL used to filter events before EQL processing
                allow_no_indices: Ignore if indices don't exist instead of returning error
                case_sensitive: Make EQL queries case-sensitive
                expand_wildcards: Expand wildcards in index names
                ignore_unavailable: Ignore unavailable indices
                keep_alive: Keep search context alive for async queries
                keep_on_completion: Keep results after completion
                result_position: Position of results to return ('head' or 'tail')
                runtime_mappings: Runtime field definitions
                tiebreaker_field: Field to sort hits with same timestamp
                wait_for_completion_timeout: Timeout for waiting on completion
                error_trace: Include error traces in response
                filter_path: Filter response to specific paths，e.g. ["hits.events._source.field1", "hits.events._source.field2"] to return only specific fields， or ["-hits.events._source.field1""] to exclude
                human: Return human-readable output
                pretty: Pretty-print JSON results

            query参数查询语法参考：
                1. 执行基础查询：使用 EQL 搜索 API 匹配单个事件 。例如，可以通过 process where process.name == "regsvr32.exe" 查找特定进程 。默认情况下，查询返回 hits.events 属性中最近的 10 条匹配事件 。   
                2. 搜索事件序列：使用 sequence 语法按时间升序查找一系列有序事件 。可以通过 with maxspan 约束整个序列发生的时间范围 。   
                3. 匹配缺失事件：在序列查询中使用 ! 符号来匹配在指定时间范围内未发生特定条件的事件 。响应中会通过 "missing": true 标识此类事件 。   
                4. 关联相同字段值：使用 by 关键字关联具有相同字段值的事件 。如果需要在序列的所有事件中共享某个字段值，可使用 sequence by 。   
                5. 定义序列失效条件：使用 until 关键字指定一个过期事件 。匹配的序列必须在该过期事件发生之前结束 。   
                6. 检索无序样本：使用 sample 语法搜索符合一个或多个关联键及过滤条件的事件 。与序列不同，样本不要求事件按时间顺序排列，甚至可以运行在没有时间戳的数据上 。   
                7. 精简响应字段：在 API 请求的 URL 中使用 filter_path 参数来过滤返回的 JSON 结果 。例如，使用 ?filter_path=-hits.events._source 可以排除体积较大的原始文档内容 。   
                8. 格式化选定字段：使用 fields 参数从索引映射中检索并格式化特定字段 。这种方式比直接引用 _source 更具优势，因为它能标准化值类型、处理字段别名并格式化日期 。   
                9. 应用运行时字段：通过 runtime_mappings 参数在搜索时提取或创建新字段 。配合 fields 参数，可以将这些实时计算的字段包含在响应中 。   
                10. 自定义核心字段：EQL 默认使用 ECS 的 @timestamp 和 event.category 。如果数据不符合此标准，可通过 timestamp_field 和 event_category_field 参数另行指定 。   
                11. 设置排序平局补偿：当多个事件具有相同时间戳时，使用 tiebreaker_field 参数指定辅助排序字段 。官方建议在 ECS 模式下使用 event.sequence 。   
                12. 执行异步搜索：通过设置 wait_for_completion_timeout 启动异步查询 。如果查询未在超时时间内完成，会返回一个搜索 ID，用户随后可使用该 ID 检查进度或检索结果 。   
                13. 管理搜索保留期：使用 keep_alive 参数更改异步搜索结果在服务器上的保留时长（默认为 5 天） 。用户也可以使用删除 API 手动清理已存储的搜索结果 。   
                14. 进行跨集群搜索：支持使用 <cluster>:<target> 语法针对远程集群运行 EQL 查询 。
                15. 函数调用：使用 stringContains、endsWith 等函数处理数据，函数名后加 ~ 可实现不区分大小写的匹配。
            """
            print(f"[DEBUG] MCP工具接收到的filter_path: {filter_path}")
            print(f"[DEBUG] filter_path类型: {type(filter_path)}")

            # 转发到实际的search_documents方法
            print(f"[INFO] 调用底层search_documents，参数filter_path={filter_path}")
            
            # 调用底层搜索方法获取原始数据
            result = self.search_client.search_documents(
                index=index,
                query=query,
                body=body,
                size=size,
                timestamp_field=timestamp_field,
                event_category_field=event_category_field,
                fetch_size=fetch_size,
                fields=fields,
                filter=filter,
                allow_no_indices=allow_no_indices,
                case_sensitive=case_sensitive,
                expand_wildcards=expand_wildcards,
                ignore_unavailable=ignore_unavailable,
                keep_alive=keep_alive,
                keep_on_completion=keep_on_completion,
                result_position=result_position,
                runtime_mappings=runtime_mappings,
                tiebreaker_field=tiebreaker_field,
                wait_for_completion_timeout=wait_for_completion_timeout,
                error_trace=error_trace,
                filter_path=filter_path,
                human=human,
                pretty=pretty
            )

            # 应用字段截断
            print(f"[DEBUG] 准备应用字段截断，EQL_MAX_FIELD_LENGTH={os.getenv('EQL_MAX_FIELD_LENGTH', '未设置')}, EQL_MAX_LIST_ITEMS={os.getenv('EQL_MAX_LIST_ITEMS', '未设置')}")
            truncated_result = apply_field_truncation(result)

            print(f"[DEBUG] 字段截断完成")
            return truncated_result
        
        @mcp.tool()
        def index_document(index: str, document: Dict, id: Optional[str] = None) -> Dict:
            """
            Creates or updates a document in the index.
            
            Args:
                index: Name of the index
                document: Document data
                id: Optional document ID
            """
            return self.search_client.index_document(index=index, id=id, document=document)
        
        @mcp.tool()
        def get_document(index: str, id: str) -> Dict:
            """
            Get a document by ID.
            
            Args:
                index: Name of the index
                id: Document ID
            """
            return self.search_client.get_document(index=index, id=id)
        
        @mcp.tool()
        def delete_document(index: str, id: str) -> Dict:
            """
            Delete a document by ID.
            
            Args:
                index: Name of the index
                id: Document ID
            """
            return self.search_client.delete_document(index=index, id=id)
        
        @mcp.tool()
        def delete_by_query(index: str, body: Dict) -> Dict:
            """
            Deletes documents matching the provided query.
            
            Args:
                index: Name of the index
                body: Query to match documents for deletion
            """
            return self.search_client.delete_by_query(index=index, body=body)
