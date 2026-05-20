"""
小红书热词数据访问对象(DAO)
提供xhs_hot_keyword表的CRUD操作
"""
import json
import logging
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from typing import Optional, List, Dict, Any, Union

import numpy as np

from .pg_db import engine

logger = logging.getLogger(__name__)


class XhsHotKeywordRecordDAO:
    """小红书热词记录数据访问对象"""

    # 创建 ThreadPoolExecutor
    thread_num = 20
    executor = ThreadPoolExecutor(max_workers=thread_num)

    # 默认参数
    default_top_k = 20
    default_similarity_threshold = 0.7

    # 表名和字段定义
    table_name = "xhs_hot_keyword"
    search_fields = "id, keyword, keyword_type, primary_label, secondary_label, business_scenario, deleted, update_time, create_time, keyword_embedding"

    def __init__(self):
        self.table_name = "xhs_hot_keyword"
        self.columns = [
            "id", "keyword", "keyword_type", "primary_label", "secondary_label",
            "business_scenario", "deleted", "update_time", "create_time", "keyword_embedding"
        ]
        self.search_fields = "id, keyword, keyword_type, primary_label, secondary_label, business_scenario, deleted, update_time, create_time, keyword_embedding"

    def insert_hot_keyword(
            self,
            keyword: str,
            keyword_type: str = "",
            primary_label: str = "",
            secondary_label: str = "",
            business_scenario: str = "",
            embedding: Optional[Union[np.ndarray, list, str]] = None,
            deleted: int = 0
    ) -> Optional[int]:
        """
        插入单条小红书热词
        """
        if not keyword:
            logger.error("XhsHotKeywordDAO_insert: keyword is required")
            return None
        try:
            fields = ["keyword", "keyword_type", "primary_label", "secondary_label",
                      "business_scenario", "deleted", "create_time", "update_time"]
            values: List[Any] = [keyword, keyword_type, primary_label, secondary_label,
                                 business_scenario, deleted, datetime.now(), datetime.now()]
            placeholders = ["%s"] * len(fields)

            embedding_str = None
            if embedding is not None:
                embedding_str = self._normalize_embedding_format(embedding, "keyword_embedding")
                if embedding_str is None:
                    logger.error("XhsHotKeywordDAO_insert: Failed to normalize embedding")
                    return None
                fields.append("keyword_embedding")
                values.append(embedding_str)
                placeholders.append("%s::vector")

            sql = f"""
                INSERT INTO {self.table_name} ({', '.join(fields)})
                VALUES ({', '.join(placeholders)})
                RETURNING id
            """
            with engine.connect() as conn:
                result = conn.exec_driver_sql(sql, tuple(values))
                inserted_id = result.scalar()
            return inserted_id
        except Exception:
            logger.exception("XhsHotKeywordDAO_insert_error")
            return None

    def batch_insert_hot_keywords(self, items: List[Dict[str, Any]]) -> List[Optional[int]]:
        """
        批量插入热词
        """
        if not items:
            return []
        results: List[Optional[int]] = []
        try:
            with engine.connect() as conn:
                for item in items:
                    try:
                        inserted_id = self.insert_hot_keyword(
                            keyword=item.get("keyword", ""),
                            keyword_type=item.get("keyword_type", "") or "",
                            primary_label=item.get("primary_label", "") or "",
                            secondary_label=item.get("secondary_label", "") or "",
                            business_scenario=item.get("business_scenario", "") or "",
                            embedding=item.get("keyword_embedding"),
                            deleted=int(item.get("deleted", 0) or 0)
                        )
                        results.append(inserted_id)
                    except Exception:
                        logger.exception("XhsHotKeywordDAO_batch_insert_single_error")
                        results.append(None)
            return results
        except Exception:
            logger.exception("XhsHotKeywordDAO_batch_insert_error")
            return [None] * len(items)

    def get_keyword_by_id(self, id: int) -> Optional[Dict[str, Any]]:
        """
        根据ID获取热词
        """
        try:
            sql = f"SELECT {self.search_fields} FROM {self.table_name} WHERE id = %s"
            with engine.connect() as conn:
                row = conn.exec_driver_sql(sql, (id,)).mappings().first()
            if not row:
                return None
            return dict(row)
        except Exception:
            logger.exception("XhsHotKeywordDAO_get_by_id_error")
            return None

    def update_keyword(
            self,
            id: int,
            keyword: Optional[str] = None,
            keyword_type: Optional[str] = None,
            primary_label: Optional[str] = None,
            secondary_label: Optional[str] = None,
            business_scenario: Optional[str] = None,
            embedding: Optional[Union[np.ndarray, list, str]] = None,
            deleted: Optional[int] = None
    ) -> bool:
        """
        更新热词信息（任意字段）
        """
        try:
            update_fields: List[str] = []
            update_values: List[Any] = []

            if keyword is not None:
                update_fields.append("keyword = %s")
                update_values.append(keyword)
            if keyword_type is not None:
                update_fields.append("keyword_type = %s")
                update_values.append(keyword_type)
            if primary_label is not None:
                update_fields.append("primary_label = %s")
                update_values.append(primary_label)
            if secondary_label is not None:
                update_fields.append("secondary_label = %s")
                update_values.append(secondary_label)
            if business_scenario is not None:
                update_fields.append("business_scenario = %s")
                update_values.append(business_scenario)
            if deleted is not None:
                update_fields.append("deleted = %s")
                update_values.append(int(deleted))
            if embedding is not None:
                embedding_str = self._normalize_embedding_format(embedding, "keyword_embedding")
                if embedding_str is None:
                    logger.error("XhsHotKeywordDAO_update: Failed to normalize embedding")
                    return False
                update_fields.append("keyword_embedding = %s::vector")
                update_values.append(embedding_str)

            if not update_fields:
                logger.warning("XhsHotKeywordDAO_update: No fields to update")
                return False

            update_fields.append("update_time = %s")
            update_values.append(datetime.now())

            update_values.append(id)
            sql = f"UPDATE {self.table_name} SET {', '.join(update_fields)} WHERE id = %s"
            with engine.connect() as conn:
                result = conn.exec_driver_sql(sql, tuple(update_values))
                return result.rowcount > 0
        except Exception:
            logger.exception("XhsHotKeywordDAO_update_error")
            return False

    def delete_keyword(self, id: int) -> bool:
        """
        逻辑删除热词
        """
        try:
            sql = f"UPDATE {self.table_name} SET deleted = 1, update_time = %s WHERE id = %s AND deleted = 0"
            with engine.connect() as conn:
                result = conn.exec_driver_sql(sql, (datetime.now(), id))
                return result.rowcount > 0
        except Exception:
            logger.exception("XhsHotKeywordDAO_delete_error")
            return False

    def restore_keyword(self, id: int) -> bool:
        """
        恢复逻辑删除的热词
        """
        try:
            sql = f"UPDATE {self.table_name} SET deleted = 0, update_time = %s WHERE id = %s AND deleted = 1"
            with engine.connect() as conn:
                result = conn.exec_driver_sql(sql, (datetime.now(), id))
                return result.rowcount > 0
        except Exception:
            logger.exception("XhsHotKeywordDAO_restore_error")
            return False

    def search_by_embedding(
            self,
            query_embedding: Union[np.ndarray, list, str],
            top_k: int = default_top_k,
            similarity_threshold: Optional[float] = None
    ) -> List[Dict[str, Any]]:
        """
        基于向量的相似检索（cosine）
        返回字段包含 similarity (1 - cosine_distance)
        """
        try:
            embedding_str = self._normalize_embedding_format(query_embedding, "keyword_embedding")
            if embedding_str is None:
                return []

            select_clause = f"{self.search_fields}, 1 - (keyword_embedding <=> %s::vector) as similarity"
            where_conditions = ["keyword_embedding IS NOT NULL", "deleted = 0"]
            params: List[Any] = [embedding_str]

            if similarity_threshold is not None:
                where_conditions.append("1 - (keyword_embedding <=> %s::vector) >= %s")
                params.extend([embedding_str, similarity_threshold])

            where_sql = " AND ".join(where_conditions)
            sql = f"""
                SELECT {select_clause}
                FROM {self.table_name}
                WHERE {where_sql}
                ORDER BY keyword_embedding <=> %s::vector ASC
                LIMIT %s
            """
            params.extend([embedding_str, top_k])
            with engine.connect() as conn:
                rows = conn.exec_driver_sql(sql, tuple(params)).mappings().all()
            results: List[Dict[str, Any]] = []
            for row in rows:
                item = dict(row)
                if "similarity" in item:
                    item["similarity"] = float(item["similarity"])
                results.append(item)
            return results
        except Exception:
            logger.exception("XhsHotKeywordDAO_search_by_embedding_error")
            return []

    def query_by_conditions(
            self,
            keyword: Optional[str] = None,
            keyword_type: Optional[str] = None,
            primary_label: Optional[str] = None,
            secondary_label: Optional[str] = None,
            business_scenario: Optional[str] = None,
            deleted: int = 0,
            page: int = 1,
            page_size: int = 10
    ) -> Dict[str, Any]:
        """
        条件查询 + 分页
        """
        try:
            where_conditions: List[str] = ["deleted = %s"]
            params: List[Any] = [int(deleted)]

            if keyword:
                where_conditions.append("keyword ILIKE %s")
                params.append(f"%{keyword}%")
            if keyword_type:
                where_conditions.append("keyword_type = %s")
                params.append(keyword_type)
            if primary_label:
                where_conditions.append("primary_label = %s")
                params.append(primary_label)
            if secondary_label:
                where_conditions.append("secondary_label = %s")
                params.append(secondary_label)
            if business_scenario:
                where_conditions.append("business_scenario = %s")
                params.append(business_scenario)

            where_sql = " AND ".join(where_conditions)
            count_sql = f"SELECT COUNT(*) FROM {self.table_name} WHERE {where_sql}"
            with engine.connect() as conn:
                total_count = conn.exec_driver_sql(count_sql, tuple(params)).scalar() or 0

            offset = (max(page, 1) - 1) * max(page_size, 1)
            data_sql = f"""
                SELECT {self.search_fields}
                FROM {self.table_name}
                WHERE {where_sql}
                ORDER BY update_time DESC
                LIMIT %s OFFSET %s
            """
            data_params = params + [page_size, offset]
            with engine.connect() as conn:
                rows = conn.exec_driver_sql(data_sql, tuple(data_params)).mappings().all()
            return {
                "total_count": int(total_count),
                "page": max(page, 1),
                "page_size": max(page_size, 1),
                "data": [dict(r) for r in rows]
            }
        except Exception:
            logger.exception("XhsHotKeywordDAO_query_by_conditions_error")
            return {
                "total_count": 0,
                "page": page,
                "page_size": page_size,
                "data": []
            }

    def _normalize_embedding_format(
            self,
            embedding: Union[np.ndarray, list, str],
            embedding_type: str = "embedding"
    ) -> Optional[str]:
        """
        统一转换embedding格式为PostgreSQL vector格式
        
        Args:
            embedding: 输入的embedding数据
            embedding_type: embedding类型，用于错误日志
        
        Returns:
            str: PostgreSQL vector格式的字符串，如 '[1,2,3]'
            None: 如果转换失败
        """
        if not embedding:
            logger.error(f"ChatbotKBService_normalize_embedding_format: Empty {embedding_type} provided")
            return None
        start_time = time.time()
        try:
            # 统一转换embedding格式
            if isinstance(embedding, np.ndarray):
                embedding_list = embedding.tolist()
            elif isinstance(embedding, str):
                try:
                    embedding_list = json.loads(embedding)
                except Exception:
                    logger.exception(f"Invalid {embedding_type} format: {embedding}")
                    return None
            elif isinstance(embedding, list):
                embedding_list = embedding
            else:
                logger.error(f"Unsupported {embedding_type} type: {type(embedding)}")
                return None

            # 转换为PostgreSQL vector格式
            embedding_str = '[' + ','.join(map(str, embedding_list)) + ']'

            return embedding_str
        except Exception:
            logger.exception(f"ChatbotKBService_normalize_embedding_format: Error normalizing {embedding_type}")
            return None


# 全局DAO实例
xhs_hot_keyword_dao = XhsHotKeywordRecordDAO()
