"""
LLM配置模块 - 基于策略模式的模型工厂
"""
import logging
import os
from abc import ABC, abstractmethod
from typing import Dict

from langchain_core.language_models import BaseLanguageModel
from langchain_openai import ChatOpenAI
from langfuse import Langfuse
from langfuse.langchain import CallbackHandler as LangfuseCallbackHandler

logger = logging.getLogger("llm-factory")


class LLMStrategy(ABC):
    """LLM策略抽象基类"""

    @abstractmethod
    def supports_model(self, model_name: str) -> bool:
        """检查是否支持指定的模型"""
        pass

    @abstractmethod
    def create_llm(self, model_name: str, **kwargs) -> BaseLanguageModel:
        """创建LLM实例"""
        pass


class OpenAIStrategy(LLMStrategy):
    """OpenAI模型策略"""

    SUPPORTED_MODELS = {
        "gpt-4", "gpt-4-turbo", "gpt-4o", "gpt-4o-mini",
        "gpt-3.5-turbo", "gpt-3.5-turbo-16k", "azure/gpt-5-chat-2025-08-07"
    }

    def supports_model(self, model_name: str) -> bool:
        return model_name in self.SUPPORTED_MODELS

    def create_llm(self, model_name: str, **kwargs) -> ChatOpenAI:
        """创建OpenAI LLM实例"""
        api_key = kwargs.pop("api_key", None)
        base_url = kwargs.pop("base_url", None)
        streaming = kwargs.pop("streaming", False)
        self.api_key = "dTcF2otlS1eoRWRnWG5BFRm3hqOzy2Thx7SzpRrGw1GS9g+SaR8K6QM1buv86FgN:pf_have_head:pf_have_head:linyang.zhong::"
        self.base_url = base_url or os.getenv("OPENAI_BASE_URL", "http://llm.api.corp.qunar.com/v1")
        default_config = {
            "model": model_name,
            "api_key": self.api_key,
            "base_url": self.base_url,
            "temperature": 0.7,
            "max_tokens": 16384,
            "streaming": streaming
        }
        # 合并用户自定义配置
        config = {**default_config, **kwargs}

        # 集成 Langfuse（硬编码客户端 + 始终追加回调）
        try:
            # 初始化 Langfuse 客户端（硬编码配置）
            Langfuse(
                public_key="pk-lf-077fcb89-7906-4bbc-b5c7-f428344a8f44",
                secret_key="sk-lf-ecdb1e6b-faba-45fb-8325-8ba2ec9f4860",
                host="http://aitrace.corp.qunar.com",
            )
            handler = LangfuseCallbackHandler()
            existing = config.get("callbacks") or []
            config["callbacks"] = [*existing, handler]
            logger.info("Langfuse 已通过硬编码方式启用并附加回调")
        except Exception as e:
            logger.warning(f"Langfuse 初始化或回调附加失败: {e}")
        logger.info(f"创建OpenAI模型: {model_name}")
        return ChatOpenAI(**config)


class LLMFactory:
    """LLM工厂类"""

    def __init__(self):
        self._strategies = [
            OpenAIStrategy(),
        ]

    def register_strategy(self, strategy: LLMStrategy):
        """注册新的策略"""
        self._strategies.append(strategy)

    def create_llm(self, model_name: str, **kwargs) -> BaseLanguageModel:
        """根据模型名称创建LLM实例"""
        for strategy in self._strategies:
            if strategy.supports_model(model_name):
                return strategy.create_llm(model_name, **kwargs)

        # 如果没有找到支持的策略，抛出异常
        supported_models = []
        for strategy in self._strategies:
            if hasattr(strategy, 'SUPPORTED_MODELS'):
                supported_models.extend(strategy.SUPPORTED_MODELS)

        raise ValueError(
            f"不支持的模型: {model_name}. "
            f"支持的模型: {', '.join(supported_models)}"
        )

    def get_supported_models(self) -> Dict[str, list]:
        """获取所有支持的模型列表"""
        models = {}
        for strategy in self._strategies:
            strategy_name = strategy.__class__.__name__.replace('Strategy', '')
            if hasattr(strategy, 'SUPPORTED_MODELS'):
                models[strategy_name] = list(strategy.SUPPORTED_MODELS)
        return models


# 全局工厂实例
llm_factory = LLMFactory()
