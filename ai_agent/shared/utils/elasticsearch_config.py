import os


def get_elasticsearch_config():
    """获取ElasticSearch配置（延迟加载，调用时才验证环境变量）"""
    es_host = os.getenv('ELASTICSEARCH_HOST')
    es_port = os.getenv('ELASTICSEARCH_PORT', '9200')
    if not es_host:
        raise ValueError("环境变量 ELASTICSEARCH_HOST 必须设置（如 localhost）")

    use_ssl = os.getenv('ELASTICSEARCH_USE_SSL', 'false').lower() == 'true'
    return {
        "host": f"{'https' if use_ssl else 'http'}://{es_host}:{es_port}",
        # ES 8.x改为keyword参数
        "use_ssl": use_ssl,
        "verify_certs": use_ssl,
        "ssl_show_warn": use_ssl,
        # 连接池保持简单config
    }


# 模块级兼容入口：首次访问时才触发环境变量读取和验证
class _ElasticsearchConfigProxy:
    _cache = None

    @classmethod
    def _ensure_loaded(cls):
        if cls._cache is None:
            cls._cache = get_elasticsearch_config()

    def __getitem__(self, key):
        self._ensure_loaded()
        return self._cache[key]

    def get(self, key, default=None):
        self._ensure_loaded()
        return self._cache.get(key, default)

    def __contains__(self, key):
        self._ensure_loaded()
        return key in self._cache


ELASTICSEARCH_CONFIG = _ElasticsearchConfigProxy()

# STTP索引配置
STTP_INDEX_PREFIX = "sttp"
STTP_INDEX_ALIAS = "sttp"
STTP_INDEX_LIFECYCLE_DAYS = 360

# ES写入配置
ES_MAX_RETRIES = 3
ES_BACKOFF_FACTOR = 2  # 指数退避
ES_BULK_SIZE = 100  # 批处理大小
ES_SHARDS = 2  # 分片数量
ES_REPLICAS = 1  # 副本数量

# STTP数据映射到ES文档的结构
STTP_ES_MAPPING = {
    "mappings": {
        "properties": {
            "id": {"type": "keyword"},
            "created_at": {"type": "date"},
            "end_at": {"type": "date"},
            "ttps": {
                "type": "nested",
                "properties": {
                    "id": {"type": "keyword"},
                    "name": {"type": "keyword"},
                    "description": {"type": "text"},
                    "techniques": {
                        "type": "nested",
                        "properties": {
                            "tech_id": {"type": "keyword"},
                            "tech_name": {"type": "keyword"},
                            "description": {"type": "text"},
                            "procedures": {"type": "text"}
                        }
                    }
                }
            },
            "event_ids": {"type": "keyword"},
            "confidence": {"type": "float"},
            "summary": {"type": "text"},
            "event_count": {"type": "integer"},
            "source_events": {"type": "keyword"},
            "attacker_ip": {"type": "keyword"},  # 攻击者IP
            "attacker_fingerprint": {"type": "object", "enabled": False}
        }
    },
    "settings": {
        "number_of_shards": ES_SHARDS,
        "number_of_replicas": ES_REPLICAS,
        "refresh_interval": "1s"  # 立即写入，适合低延时要求
    }
}

# 查询接口返回的保留字段
STTP_API_RESPONSE_FIELDS = [
    "id", "created_at", "end_at", "ttps", "event_ids",
    "confidence", "summary", "event_count", "source_events",
    "attacker_fingerprint", "attacker_ip", "timestamp"  # 添加 attacker_ip
]