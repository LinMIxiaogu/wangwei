import logging
from typing import List, Dict, Any, Optional

from src.database.xhs_hot_keyword_dao import xhs_hot_keyword_dao
from src.graph.llm.embedding_model import get_default_m3e_model, M3EEmbeddingModel

logger = logging.getLogger(__name__)


class XhsHotKeywordService:
    """
    小红书热词服务
    
    - 提供热词的新增、批量导入、查询、更新、删除
    - 提供基于文本的向量检索（pgvector cosine）
    """

    def __init__(self, embedding_model: Optional[M3EEmbeddingModel] = None):
        self.embedding_model = embedding_model or get_default_m3e_model()

    def _generate_embedding(self, text: str) -> Optional[List[float]]:
        """
        为文本生成 embedding 向量
        """
        try:
            text_norm = (text or "").strip()
            if not text_norm:
                return None
            return self.embedding_model.encode_single(text_norm)
        except Exception:
            logger.exception(f"XhsHotKeywordService_generate_embedding_error: text:{text[:50] if text else ''}")
            return None

    def add_hot_keyword(
            self,
            keyword: str,
            keyword_type: str = "",
            primary_label: str = "",
            secondary_label: str = "",
            business_scenario: str = "",
            auto_embedding: bool = True,
            embedding: Optional[List[float]] = None,
            deleted: int = 0
    ) -> Optional[int]:
        """
        新增单条热词
        """
        if not keyword or not keyword.strip():
            logger.error("XhsHotKeywordService_add_hot_keyword: keyword is required")
            return None
        try:
            keyword_embedding = embedding
            if auto_embedding and embedding is None:
                keyword_embedding = self._generate_embedding(keyword + "," + primary_label + "," + secondary_label)
                if keyword_embedding is None:
                    logger.warning(
                        f"XhsHotKeywordService_add_hot_keyword: Failed to generate embedding for keyword: {keyword[:50]}...")
            return xhs_hot_keyword_dao.insert_hot_keyword(
                keyword=keyword.strip(),
                keyword_type=keyword_type or "",
                primary_label=primary_label or "",
                secondary_label=secondary_label or "",
                business_scenario=business_scenario or "",
                embedding=keyword_embedding,
                deleted=int(deleted or 0),
            )
        except Exception:
            logger.exception("XhsHotKeywordService_add_hot_keyword_error")
            return None

    def add_hot_keywords_batch(
            self,
            items: List[Dict[str, Any]],
            auto_embedding: bool = True
    ) -> List[Optional[int]]:
        """
        批量插入热词
        items: [
          {
            "keyword": "...",
            "keyword_type": "...",
            "primary_label": "...",
            "secondary_label": "...",
            "business_scenario": "...",
            "keyword_embedding": [...],   # 可选
            "deleted": 0
          }, ...
        ]
        """
        if not items:
            logger.error("XhsHotKeywordService_add_hot_keywords_batch: empty items")
            return []
        try:
            prepared: List[Dict[str, Any]] = []
            for i, it in enumerate(items):
                kw = (it.get("keyword") or "").strip()
                if not kw:
                    logger.error(f"XhsHotKeywordService_add_hot_keywords_batch: Item {i} missing keyword")
                    prepared.append({"__skip__": True})
                    continue
                entry = {
                    "keyword": kw,
                    "keyword_type": it.get("keyword_type", "") or "",
                    "primary_label": it.get("primary_label", "") or "",
                    "secondary_label": it.get("secondary_label", "") or "",
                    "business_scenario": it.get("business_scenario", "") or "",
                    "deleted": int(it.get("deleted", 0) or 0),
                }
                emb = it.get("keyword_embedding")
                if auto_embedding and emb is None:
                    emb = self._generate_embedding(kw)
                    if emb is None:
                        logger.warning(
                            f"XhsHotKeywordService_add_hot_keywords_batch: failed to embed keyword: {kw[:50]}...")
                if emb is not None:
                    entry["keyword_embedding"] = emb
                prepared.append(entry)

            # 过滤 skip
            valid = [p for p in prepared if "__skip__" not in p]
            if not valid:
                return [None] * len(items)

            return xhs_hot_keyword_dao.batch_insert_hot_keywords(valid)
        except Exception:
            logger.exception("XhsHotKeywordService_add_hot_keywords_batch_error")
            return [None] * len(items)

    def import_hot_keywords(
            self,
            data: List[Dict[str, Any]],
            auto_embedding: bool = True
    ) -> Dict[str, Any]:
        """
        批量导入简化格式的热词数据：
        [
          { "keyword": "xxx", "keyword_type": "...", "primary_label": "...", "secondary_label": "...", "business_scenario": "..." },
          ...
        ]
        """
        if not data:
            return {"total": 0, "success": 0, "failed": 0, "success_ids": [], "failed_items": []}
        total = len(data)
        success_ids: List[int] = []
        failed_items: List[str] = []
        try:
            for i, item in enumerate(data):
                try:
                    kw = (item.get("keyword") or "").strip()
                    if not kw:
                        failed_items.append(f"Item {i}: missing keyword")
                        continue
                    kid = self.add_hot_keyword(
                        keyword=kw,
                        keyword_type=item.get("keyword_type", "") or "",
                        primary_label=item.get("primary_label", "") or "",
                        secondary_label=item.get("secondary_label", "") or "",
                        business_scenario=item.get("business_scenario", "") or "",
                        auto_embedding=auto_embedding,
                        embedding=item.get("keyword_embedding"),
                        deleted=int(item.get("deleted", 0) or 0),
                    )
                    if kid is not None:
                        success_ids.append(kid)
                    else:
                        failed_items.append(f"Item {i}: insert failed")
                except Exception as e:
                    failed_items.append(f"Item {i}: {str(e)}")
            return {
                "total": total,
                "success": len(success_ids),
                "failed": len(failed_items),
                "success_ids": success_ids,
                "failed_items": failed_items,
            }
        except Exception as e:
            logger.exception("XhsHotKeywordService_import_hot_keywords_error")
            return {
                "total": total,
                "success": len(success_ids),
                "failed": total - len(success_ids),
                "success_ids": success_ids,
                "failed_items": failed_items or [f"System error: {str(e)}"],
            }

    def search_by_text(
            self,
            query: str,
            top_k: int = 20,
            similarity_threshold: Optional[float] = None
    ) -> List[Dict[str, Any]]:
        """
        基于文本进行相似检索（会自动生成查询向量）
        """
        if not query or not query.strip():
            logger.error("XhsHotKeywordService_search_by_text: empty query")
            return []
        try:
            emb = self._generate_embedding(query.strip())
            if emb is None:
                return []
            return xhs_hot_keyword_dao.search_by_embedding(
                query_embedding=emb,
                top_k=top_k,
                similarity_threshold=similarity_threshold,
            )
        except Exception:
            logger.exception("XhsHotKeywordService_search_by_text_error")
            return []

    def query_hot_keywords(
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
            return xhs_hot_keyword_dao.query_by_conditions(
                keyword=keyword,
                keyword_type=keyword_type,
                primary_label=primary_label,
                secondary_label=secondary_label,
                business_scenario=business_scenario,
                deleted=deleted,
                page=page,
                page_size=page_size,
            )
        except Exception:
            logger.exception("XhsHotKeywordService_query_hot_keywords_error")
            return {"total_count": 0, "page": page, "page_size": page_size, "data": []}

    def get_hot_keyword(self, id: int) -> Optional[Dict[str, Any]]:
        """
        根据ID获取热词
        """
        try:
            return xhs_hot_keyword_dao.get_keyword_by_id(id)
        except Exception:
            logger.exception("XhsHotKeywordService_get_hot_keyword_error")
            return None

    def update_hot_keyword(
            self,
            id: int,
            keyword: Optional[str] = None,
            keyword_type: Optional[str] = None,
            primary_label: Optional[str] = None,
            secondary_label: Optional[str] = None,
            business_scenario: Optional[str] = None,
            auto_embedding: bool = True,
            embedding: Optional[List[float]] = None,
            deleted: Optional[int] = None
    ) -> bool:
        """
        更新热词任意字段；当 keyword 变更且启用 auto_embedding 时自动重算 embedding
        """
        try:
            new_embedding = embedding
            if auto_embedding and embedding is None and keyword:
                emb = self._generate_embedding(keyword)
                if emb is None:
                    logger.warning(
                        f"XhsHotKeywordService_update_hot_keyword: failed to embed keyword: {keyword[:50]}...")
                new_embedding = emb
            return xhs_hot_keyword_dao.update_keyword(
                id=id,
                keyword=keyword,
                keyword_type=keyword_type,
                primary_label=primary_label,
                secondary_label=secondary_label,
                business_scenario=business_scenario,
                embedding=new_embedding,
                deleted=deleted,
            )
        except Exception:
            logger.exception("XhsHotKeywordService_update_hot_keyword_error")
            return False

    def delete_hot_keyword(self, id: int) -> bool:
        """
        逻辑删除热词
        """
        try:
            return xhs_hot_keyword_dao.delete_keyword(id)
        except Exception:
            logger.exception("XhsHotKeywordService_delete_hot_keyword_error")
            return False

    def restore_hot_keyword(self, id: int) -> bool:
        """
        恢复逻辑删除的热词
        """
        try:
            return xhs_hot_keyword_dao.restore_keyword(id)
        except Exception:
            logger.exception("XhsHotKeywordService_restore_hot_keyword_error")
            return False


# 便捷函数和默认实例
_default_xhs_hot_keyword_service: Optional[XhsHotKeywordService] = None


def get_default_xhs_hot_keyword_service() -> XhsHotKeywordService:
    """
    获取默认的小红书热词服务实例（单例模式）
    """
    global _default_xhs_hot_keyword_service
    if _default_xhs_hot_keyword_service is None:
        _default_xhs_hot_keyword_service = XhsHotKeywordService()
    return _default_xhs_hot_keyword_service
