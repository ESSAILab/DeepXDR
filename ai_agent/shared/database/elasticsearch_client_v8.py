"""
ElasticSearch v8兼容客户端封装
对ES 8.x版本的适配处理
"""
import logging
from datetime import datetime
from typing import Dict, List, Optional, Any
from elasticsearch import Elasticsearch
from elasticsearch.helpers import bulk
from shared.database.es_common import ESError, get_es_connection_config

from shared.utils.elasticsearch_config import (
    ELASTICSEARCH_CONFIG, STTP_INDEX_PREFIX, STTP_INDEX_ALIAS,
    STTP_ES_MAPPING, ES_MAX_RETRIES, ES_BACKOFF_FACTOR, ES_BULK_SIZE
)

logger = logging.getLogger(__name__)


class ElasticsearchClientV8:
    """ElasticSearch v8客户端封装"""

    def __init__(self):
        self.client: Optional[Elasticsearch] = None
        self._connect()

    def _connect(self):
        """建立ES连接 - ES 8.0要求完整URL"""
        try:
            # ES 8.x需要完整URL格式
            es_host = ELASTICSEARCH_CONFIG['host']

            # 使用ES v8标准的key=value连接方式
            self.client = Elasticsearch(
                hosts=[es_host],
                basic_auth=ELASTICSEARCH_CONFIG.get('basic_auth'),
                verify_certs=ELASTICSEARCH_CONFIG.get('verify_certs', True),
                ssl_show_warn=ELASTICSEARCH_CONFIG.get('ssl_show_warn', True),
                **get_es_connection_config(),
                max_retries=ES_MAX_RETRIES,
                retry_on_status=[502, 503, 504, 429]  # 需要重试的状态码
            )

            # 测试连接
            if self.client.ping():
                logger.info(f"ElasticSearch(v8)连接成功: {es_host}")
            else:
                raise ConnectionError("ElasticSearch连接失败")

        except (ESError, ConnectionError, TimeoutError) as e:
            logger.error(f"ElasticSearch连接异常: {e}")
            logger.error(f"尝试连接的ES主机: {es_host}")
            logger.error("确保ELASTICSEARCH_HOST和ELASTICSEARCH_PORT(9201)环境变量设置正确")
            raise

        except Exception as e:
            logger.exception(f"未预期错误: {e}")
            raise
    def save_sttp(self, sttp_doc: Dict[str, Any]) -> bool:
        """保存单个STTP文档"""
        try:
            index_name = self.get_index_name()
            doc_id = sttp_doc.get("id")

            # ES v8 创建索引（如果必要）
            if not self._index_exists(index_name):
                self._create_index(index_name)
                # 新创建索引后添加别名
                self.add_alias()

            # ES 8.x兼容的记录方式
            response = self.client.index(
                index=index_name,
                id=doc_id,
                document=sttp_doc,
                refresh=True
            )

            logger.debug(f"STTP保存成功 - ID: {doc_id}, Index: {index_name}, Result: {response.get('result', 'created')}")
            return True

        except (ESError, ConnectionError, TimeoutError, ValueError, TypeError) as e:
            logger.error(f"保存STTP失败: {e}")
            return False

        except Exception as e:
            logger.exception(f"未预期错误: {e}")
            raise
    def _index_exists(self, index_name: str) -> bool:
        """检查索引是否存在"""
        try:
            return self.client.indices.exists(index=index_name)
        except (ESError, ConnectionError, TimeoutError):
            return False

    def _create_index(self, index_name: str):
        """创建索引 - ES 8.x兼容版，包含完整mapping"""
        try:
            # ES 8.x需要完整的mapping信息
            body = {
                "mappings": STTP_ES_MAPPING.get('mappings', {}),
                "settings": STTP_ES_MAPPING.get('settings', {})
            }
            self.client.indices.create(index=index_name, body=body)
            logger.info(f"创建索引: {index_name}，包含完整mapping")
        except (ESError, ConnectionError, TimeoutError) as e:
            logger.warning(f"索引可能已存在或创建失败: {e}")

        except Exception as e:
            logger.exception(f"未预期错误: {e}")
            raise
    def bulk_save_sttp(self, sttp_docs: List[Dict[str, Any]]) -> bool:
        """批量保存STTP文档"""
        if not sttp_docs:
            return True

        try:
            index_name = self.get_index_name()

            # ES v8 创建索引（如果必要）
            if not self._index_exists(index_name):
                self._create_index(index_name)
                # 新创建索引后添加别名
                self.add_alias()

            # 构建批量操作
            actions = []
            for doc in sttp_docs:
                action = {
                    "_index": index_name,
                    "_id": doc.get("id"),
                    "_source": doc
                }
                actions.append(action)

            # ES 8.x兼容的批量写入
            bulk_response = bulk(
                self.client,
                actions,
                chunk_size=ES_BULK_SIZE,
                initial_backoff=ES_BACKOFF_FACTOR
            )

            success_count = len(bulk_response[0])
            logger.info(f"批量保存成功 - 成功数量: {success_count}, 索引: {index_name}")
            return True

        except (ESError, ConnectionError, TimeoutError, ValueError, TypeError) as e:
            logger.error(f"批量保存STTP失败: {e}")
            return False

        except Exception as e:
            logger.exception(f"未预期错误: {e}")
            raise
    def search_ttps_with_filter(self, start_time: Optional[datetime] = None,
                               end_time: Optional[datetime] = None,
                               min_confidence: float = 0.0,
                               max_confidence: float = 1.0,
                               offset: int = 0, limit: int = 100) -> Dict[str, Any]:
        """根据过滤条件获取STTP列表 - 适配elastic_repositories期望的接口"""
        # 构建查询
        must_conditions = []

        # 时间范围过滤
        if start_time or end_time:
            time_range = {}
            if start_time:
                time_range["gte"] = start_time.isoformat()
            if end_time:
                time_range["lte"] = end_time.isoformat()
            must_conditions.append({
                "range": {
                    "created_at": time_range
                }
            })

        # 置信度过滤
        if min_confidence > 0 or max_confidence < 1:
            must_conditions.append({
                "range": {
                    "confidence": {
                        "gte": min_confidence,
                        "lte": max_confidence
                    }
                }
            })

        # 构建最终查询
        query = {"bool": {"must": must_conditions}} if must_conditions else {"match_all": {}}

        sort = [{"created_at": {"order": "desc"}}]

        # 执行搜索
        return self.search_sttp(query=query, offset=offset, limit=limit, sort=sort)

    def search_sttp(self, query: Optional[Dict[str, Any]] = None, offset: int = 0,
                   limit: int = 100, sort: Optional[List[Any]] = None) -> Dict[str, Any]:
        """搜索STTP文档 - ES 8.x简化版"""
        try:
            query_body = {
                "from": offset,
                "size": limit,
                "track_total_hits": True,
                "query": query or {"match_all": {}},
                "sort": sort or [{"created_at": {"order": "desc"}}]
            }

            response = self.client.search(
                index=STTP_INDEX_ALIAS,
                body=query_body
            )

            hits = response["hits"]["hits"]
            total = response["hits"]["total"]["value"]

            results = [hit["_source"] for hit in hits]

            return {
                "items": results,
                "total": total,
                "took": response.get("took", 0)
            }

        except (ESError, ConnectionError, TimeoutError, ValueError, TypeError) as e:
            logger.error(f"搜索STTP失败: {e}")
            return {"items": [], "total": 0, "took": 0}

        except Exception as e:
            logger.exception(f"未预期错误: {e}")
            raise
    def get_sttp_by_id(self, sttp_id: str) -> Optional[Dict[str, Any]]:
        """根据ID获取STTP文档"""
        try:
            # 直接通过通配符在所有 sttp-* 索引中搜索
            wildcard_index = f"{STTP_INDEX_PREFIX}*"
            logger.debug(f"在索引通配符 {wildcard_index} 中搜索文档: {sttp_id}")
            response = self.client.search(
                index=wildcard_index,
                body={
                    "query": {"ids": {"values": [sttp_id]}},
                    "size": 1
                },
                ignore_unavailable=True,
                allow_no_indices=True
            )
            hits = response.get("hits", {}).get("hits", [])
            if hits:
                hit = hits[0]
                doc_source = hit.get("_source")
                idx = hit.get("_index")
                logger.info(f"在索引 {idx} 中找到文档 {sttp_id}")

                # 自动添加索引到别名，避免下次查询失败
                if idx:
                    try:
                        self.client.indices.update_aliases(
                            actions=[{"add": {"index": idx, "alias": STTP_INDEX_ALIAS}}]
                        )
                        logger.info(f"已自动将索引 {idx} 添加到别名 {STTP_INDEX_ALIAS}")
                    except (ESError, ConnectionError, TimeoutError) as alias_err:
                        logger.warning(f"添加索引 {idx} 到别名失败: {alias_err}")

                return doc_source

            logger.debug(f"在所有 sttp 索引中均未找到文档 - ID: {sttp_id}")
            return None

        except (ESError, ConnectionError, TimeoutError, ValueError, TypeError) as e:
            logger.error(f"获取STTP失败 - ID: {sttp_id}, 错误: {e}")
            return None

        except Exception as e:
            logger.exception(f"未预期错误: {e}")
            raise
    def search_ttps_by_filters(self, query_body: Dict) -> Dict[str, Any]:
        """搜索STTP（支持复杂查询）"""
        return self.search_sttp(query_body.get('query'))

    def get_sttp_stats(self) -> Dict[str, Any]:
        """获取STTP统计信息"""
        try:
            stats_body = {
                "size": 0,
                "aggs": {
                    "total_count": {
                        "value_count": {"field": "id"}
                    },
                    "max_confidence": {
                        "max": {"field": "confidence"}
                    },
                    "avg_confidence": {
                        "avg": {"field": "confidence"}
                    },
                    "event_total": {
                        "sum": {"field": "event_count"}
                    }
                }
            }
            response = self.client.search(
                index=STTP_INDEX_ALIAS,
                body=stats_body
            )
            aggs = response["aggregations"]

            # 计算不同风险等级的TTP数量 - 处理可能的None值
            high_risk = self._count_by_confidence_range(0.7, 1.0)
            medium_risk = self._count_by_confidence_range(0.3, 0.7)
            low_risk = self._count_by_confidence_range(0.0, 0.3)

            return {
                "total_ttps": aggs["total_count"].get("value", 0),
                "max_confidence": aggs["max_confidence"].get("value", 0.0),
                "avg_confidence": aggs["avg_confidence"].get("value", 0.0),
                "total_events": aggs["event_total"].get("value", 0),
                "high_risk_ttps": high_risk,
                "medium_risk_ttps": medium_risk,
                "low_risk_ttps": low_risk
            }

        except (ESError, ConnectionError, TimeoutError, ValueError, TypeError) as e:
            logger.error(f"获取STTP统计失败: {e}")
            return {
                "total_ttps": 0,
                "max_confidence": 0.0,
                "avg_confidence": 0.0,
                "total_events": 0,
                "high_risk_ttps": 0,
                "medium_risk_ttps": 0,
                "low_risk_ttps": 0
            }

        except Exception as e:
            logger.exception(f"未预期错误: {e}")
            raise
    def _count_by_confidence_range(self, min_val: float, max_val: float) -> int:
        """根据置信度范围统计数量"""
        try:
            range_query = {
                "size": 0,
                "query": {
                    "range": {
                        "confidence": {
                            "gte": min_val,
                            "lte": max_val
                        }
                    }
                },
                "aggs": {
                    "count": {
                        "value_count": {"field": "id"}
                    }
                }
            }
            response = self.client.search(
                index=STTP_INDEX_ALIAS,
                body=range_query
            )
            return response.get("aggs", {}).get("count", {}).get("value", 0)
        except (ESError, ConnectionError, TimeoutError, ValueError, TypeError):
            return 0

    def get_index_name(self) -> str:
        """获取当前日期的索引名"""
        return f"{STTP_INDEX_PREFIX}-{datetime.now().strftime('%Y.%m.%d').replace('-', '.')}"

    def get_all_sttp_indices(self) -> List[str]:
        """获取所有存在的 sttp-* 索引列表"""
        try:
            indices = self.client.indices.get(index=f"{STTP_INDEX_PREFIX}*")
            return list(indices.keys())
        except (ESError, ConnectionError, TimeoutError) as e:
            logger.debug(f"获取sttp索引列表失败: {e}")
            return []

        except Exception as e:
            logger.exception(f"未预期错误: {e}")
            raise
    def add_alias(self):
        """给所有sttp索引添加别名，保留历史索引别名，不移除旧索引"""
        try:
            alias_name = STTP_INDEX_ALIAS

            # 获取所有存在的sttp索引
            all_sttp_indices = self.get_all_sttp_indices()

            if not all_sttp_indices:
                logger.debug(f"未找到任何 {STTP_INDEX_PREFIX}* 索引")
                return

            # 获取当前已绑定到别名的索引
            try:
                current_alias_info = self.client.indices.get_alias(name=alias_name)
                aliased_indices = set(current_alias_info.keys())
            except (ESError, ConnectionError, TimeoutError):
                # 别名不存在
                aliased_indices = set()

            # 找出需要添加别名的索引（还没有绑定的）
            indices_to_alias = set(all_sttp_indices) - aliased_indices

            if indices_to_alias:
                # 批量添加别名
                actions = [{"add": {"index": idx, "alias": alias_name}} for idx in indices_to_alias]
                self.client.indices.update_aliases(actions=actions)
                logger.info(f"已为 {len(indices_to_alias)} 个sttp索引添加别名 '{alias_name}': {indices_to_alias}")
            else:
                logger.debug(f"所有sttp索引已绑定到别名 '{alias_name}'，共 {len(aliased_indices)} 个")

        except (ESError, ConnectionError, TimeoutError, ValueError, TypeError) as e:
            logger.error(f"添加别名 '{STTP_INDEX_ALIAS}' 失败: {e}")

        except Exception as e:
            logger.exception(f"未预期错误: {e}")
            raise
    def close(self):
        """关闭ES连接"""
        if self.client:
            self.client.close()
            logger.info("ElasticSearch连接已关闭")


# 全局ES客户端实例
es_client: Optional[ElasticsearchClientV8] = None


def get_es_client() -> ElasticsearchClientV8:
    """获取全局ES客户端实例"""
    global es_client
    if es_client is None:
        es_client = ElasticsearchClientV8()
    return es_client
