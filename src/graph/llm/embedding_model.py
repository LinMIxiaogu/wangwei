import logging
import os
from abc import ABC, abstractmethod
from typing import List, Union, Optional, Dict, Any

import requests

logger = logging.getLogger(__name__)
import time
from pyrate_limiter import Duration, Limiter, Rate


class EmbeddingModel(ABC):
    """Embedding 模型抽象基类"""

    def __init__(self, model_name: str = "base"):
        """
        初始化 Embedding 模型
        
        Args:
            model_name: 模型名称
        """
        self.model_name = model_name

    @abstractmethod
    def encode_single(self, text: str, **kwargs) -> Optional[List[float]]:
        """
        对单个文本进行编码，生成 embedding 向量
        
        Args:
            text: 输入文本
            **kwargs: 其他参数
            
        Returns:
            List[float]: embedding 向量，失败返回 None
        """
        pass

    @abstractmethod
    def encode_batch(self, texts: List[str], **kwargs) -> List[Optional[List[float]]]:
        """
        对批量文本进行编码，生成 embedding 向量
        
        Args:
            texts: 输入文本列表
            **kwargs: 其他参数
            
        Returns:
            List[Optional[List[float]]]: embedding 向量列表，失败的项为 None
        """
        pass

    def encode(self, text_or_texts: Union[str, List[str]], **kwargs) -> Union[
        Optional[List[float]], List[Optional[List[float]]]]:
        """
        统一的编码接口，自动判断单个文本还是批量文本
        
        Args:
            text_or_texts: 单个文本或文本列表
            **kwargs: 其他参数
            
        Returns:
            单个文本返回 List[float] 或 None，批量文本返回 List[Optional[List[float]]]
        """
        if isinstance(text_or_texts, str):
            return self.encode_single(text_or_texts, **kwargs)
        elif isinstance(text_or_texts, list):
            return self.encode_batch(text_or_texts, **kwargs)
        else:
            logger.error(f"EmbeddingModel_encode: Unsupported input type: {type(text_or_texts)}")
            return None


class M3EEmbeddingModel(EmbeddingModel):
    """M3E Embedding 模型，集成 Qunar 的 embedding 接口"""

    def __init__(
            self
    ):
        super().__init__(model_name="m3e-base")
        self.url = os.getenv("EMBEDDING_URL")
        self.key = os.getenv("EMBEDDING_KEY")
        self.password = os.getenv("EMBEDDING_PASSWORD")
        self.api_type = os.getenv("EMBEDDING_API_TYPE")
        self.app_code = os.getenv("EMBEDDING_APP_CODE")
        self.project = os.getenv("EMBEDDING_PROJECT")
        self.user_identity = os.getenv("EMBEDDING_USER_IDENTITY")
        self.timeout = int(os.getenv("EMBEDDING_TIMEOUT", "60"))
        self.limiter = Limiter(Rate(1, Duration.SECOND), max_delay=10000, retry_until_max_delay=False)

    def _make_request(self, texts: List[str]) -> Optional[Dict[str, Any]]:
        """
        发送 API 请求
        
        Args:
            texts: 文本列表
            
        Returns:
            Dict: API 响应结果，失败返回 None
        """
        start_time = time.time()
        if not texts:
            logger.warning("M3EEmbeddingModel_make_request: Empty texts provided for embedding request")
            return None

        # 构建请求数据
        request_data = {
            "key": self.key,
            "password": self.password,
            "prompt": texts,
            "apiType": self.api_type,
            "traceId": "1",
            "appCode": self.app_code,
            "project": self.project,
            "userIdentityInfo": self.user_identity
        }
        try:
            self.limiter.try_acquire("m3e_embedding")
            response = requests.post(
                self.url,
                data=request_data,
                timeout=self.timeout
            )
            # 检查 HTTP 状态码
            if response is None or response.status_code != 200:
                logger.error(
                    f"M3EEmbeddingModel_make_request: Failed to get valid response from embedding API, status_code:{response.status_code if response is not None else 'None'}")
                return None
            return response.json()
        except Exception:
            logger.exception(f"M3EEmbeddingModel_make_request_error,texts:{texts}")
        return None

    def _extract_embeddings(self, response: Dict[str, Any], expected_count: int) -> List[Optional[List[float]]]:
        """
        从API响应中提取embedding向量
        
        Args:
            response: API响应字典，格式为 {"status": 0, "message": "请求成功", "data": {"embeddings": [[...]]}}
            expected_count: 期望的向量数量
            
        Returns:
            提取的向量列表，失败的位置为None
        """
        start_time = time.time()
        try:
            # 检查响应状态
            if response.get('status') != 0:
                logger.error(
                    f"M3EEmbeddingModel_extract_embeddings_error: API returned error status: {response.get('status')}, message: {response.get('message')}")
                return [None] * expected_count

            # 直接获取 data.embeddings
            embeddings_data = response.get('data', {}).get('embeddings', [])

            if not isinstance(embeddings_data, list):
                logger.error(
                    f"M3EEmbeddingModel_extract_embeddings: Invalid embeddings data format: {type(embeddings_data)}")
                return [None] * expected_count

            # 验证每个向量都是数字列表
            embeddings = []
            for i, embedding in enumerate(embeddings_data):
                if isinstance(embedding, list) and all(isinstance(x, (int, float)) for x in embedding):
                    embeddings.append(embedding)
                else:
                    logger.error(
                        f"M3EEmbeddingModel_extract_embeddings: Invalid embedding format at index {i}: {type(embedding)}")
                    embeddings.append(None)

            # 检查数量是否匹配
            if len(embeddings) != expected_count:
                logger.warning(
                    f"M3EEmbeddingModel_extract_embeddings: Expected {expected_count} embeddings, got {len(embeddings)}")
                # 补齐或截断
                while len(embeddings) < expected_count:
                    embeddings.append(None)
                embeddings = embeddings[:expected_count]

            return embeddings

        except Exception:
            logger.exception(
                f"M3EEmbeddingModel_extract_embeddings_error: Error extracting embeddings,response:{response},expected_count:{expected_count}")
            return [None] * expected_count

    def encode_single(self, text: str, **kwargs) -> Optional[List[float]]:
        """
        对单个文本进行编码
        
        Args:
            text: 输入文本
            **kwargs: 其他参数
            
        Returns:
            List[float]: embedding 向量，失败返回 None
        """
        start_time = time.time()
        if not text or not text.strip():
            logger.error("M3EEmbeddingModel_encode_single: Empty or whitespace-only text provided")
            return None
        try:
            # 调用批量接口
            results = self.encode_batch([text.strip()], **kwargs)
            return results[0] if results else None
        except Exception:
            logger.exception(
                f"M3EEmbeddingModel_encode_single_error: Error encoding single text,text:{text},**kwargs:{kwargs}")
            return None

    def encode_batch(self, texts: List[str], **kwargs) -> List[Optional[List[float]]]:
        """
        对批量文本进行编码
        
        Args:
            texts: 输入文本列表
            **kwargs: 其他参数
            
        Returns:
            List[Optional[List[float]]]: embedding 向量列表
        """
        start_time = time.time()
        results = [None] * len(texts)
        if not texts:
            logger.error("M3EEmbeddingModel_encode_batch: Empty text list provided")
            return results
        try:
            # 发送请求
            response = self._make_request(texts)
            if response is None or 'status' not in response or response['status'] != 0:
                logger.error(
                    f"M3EEmbeddingModel_encode_batch: Failed to get valid response from embedding API, response: {response}")
                return [None] * len(texts)
            # 提取 embedding 向量
            embeddings = self._extract_embeddings(response, len(texts))
            for i, text in enumerate(texts):
                if i < len(embeddings):
                    results[i] = embeddings[i]
            return results
        except Exception:
            logger.exception(
                f"M3EEmbeddingModel_encode_batch_error: Error encoding batch texts,texts:{texts},**kwargs：{kwargs}")
            return [None] * len(texts)


# 便捷函数和默认实例
def create_m3e_model(**kwargs) -> M3EEmbeddingModel:
    """
    创建 M3E Embedding 模型实例的便捷函数
    
    Args:
        **kwargs: 模型初始化参数
        
    Returns:
        M3EEmbeddingModel: 模型实例
    """
    return M3EEmbeddingModel(**kwargs)


# 默认模型实例（可选）
default_m3e_model = None


def get_default_m3e_model() -> M3EEmbeddingModel:
    """
    获取默认的 M3E 模型实例（单例模式）
    
    Returns:
        M3EEmbeddingModel: 默认模型实例
    """
    global default_m3e_model
    if default_m3e_model is None:
        default_m3e_model = M3EEmbeddingModel()
    return default_m3e_model
