# 根据ES版本选择正确的异常处理方式
try:
    from elasticsearch.exceptions import ElasticsearchException as ESError
except ImportError:
    try:
        from elasticsearch import ApiError as ESError
    except ImportError:
        # 如果都导入失败，使用通用异常作为fallback
        ESError = Exception

# ES 8兼容性连接参数
def get_es_connection_config():
    """获取ES连接配置"""
    return {
        "retry_on_timeout": True,
        "request_timeout": 30,
    }