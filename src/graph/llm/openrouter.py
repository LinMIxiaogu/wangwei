import asyncio
import os
from typing import Any, Dict

from dotenv import load_dotenv
from langchain_core.messages import SystemMessage, HumanMessage
from langchain_openai import ChatOpenAI, OpenAI

from src.graph.llm.OpenRouterImageModel import OpenRouterImageModel
from src.graph.llm.QunarImageModel import QunarImageModel

# 判断是否为本地开发环境
# 如果 APP_CODE_ENV_NAME 已经在环境变量中设置，说明是部署环境，不需要加载 .env 文件
# 如果没有设置，说明是本地开发环境，需要加载 .env 文件
if 'APP_CODE_ENV_NAME' not in os.environ:
    # 本地开发环境：尝试加载 .env 文件
    env_files_to_try = ['.env.beta', '.env.dev', '.env.local', '.env']
    loaded = False
    
    for env_file in env_files_to_try:
        if os.path.exists(env_file):
            load_dotenv(env_file)
            print(f"本地开发环境已加载配置: {env_file}")
            loaded = True
            break
    
    if not loaded:
        load_dotenv()  # 尝试加载默认环境变量
        print("本地开发环境: 未找到 .env 文件，使用系统环境变量")
else:
    # 部署环境：环境变量已通过启动脚本设置，不需要加载 .env 文件
    env_name = os.getenv('APP_CODE_ENV_NAME')
    print(f"部署环境 ({env_name}): 使用启动脚本设置的环境变量")


def _parse_float(value: Any, default: float) -> float:
    try:
        return float(value)
    except Exception:
        return default


def _parse_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except Exception:
        return default


def _biz_env_key(biz_name: str, key: str) -> str:
    return f"LLM_BIZ_{biz_name.upper().replace('-', '_')}_{key}"


def _prefix_for_biz(biz_name: str) -> str:
    b = biz_name.strip().lower().replace('-', '_')
    if b == "reasoning":
        return "REASONING"
    if b == "basic_fallback":
        return "BASIC_FALLBACK"
    return "BASIC" if b == "basic" else biz_name.upper().replace('-', '_')


def _env_for_biz(biz_name: str) -> Dict[str, Any]:
    p = _prefix_for_biz(biz_name)
    return {
        "api_key": os.getenv(f"{p}_API_KEY"),
        "base_url": os.getenv(f"{p}_BASE_URL"),
        "model": os.getenv(f"{p}_MODEL"),
        "temperature": os.getenv(f"{p}_TEMPERATURE"),
        "max_tokens": os.getenv(f"{p}_MAX_TOKENS"),
    }


# 1. 定义一个简单的图片生成包装类 (绕过 LangChain 的解析)
class OpenRouterImageClient:
    def __init__(self, model: str, api_key: str, base_url: str, **kwargs):
        self.client = OpenAI(api_key=api_key, base_url=base_url)
        self.model = model
        self.kwargs = kwargs

    def generate(self, prompt: str):
        """
        尝试使用 Chat 接口请求生图 (针对 Gemini 等多模态模型)
        并返回原始的 JSON 响应，方便调试寻找图片数据
        """
        # 注意：不同的模型生图接口不同。
        # DALL-E 走 images.generate
        # Gemini 走 chat.completions，但返回的是非标准结构

        try:
            # 优先尝试 Chat 接口 (因为你用的是 Gemini 模型)
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[{"role": "user", "content": prompt}],
                **self.kwargs
            )
            # 直接返回原始对象，不进行任何封装
            return response
        except Exception as e:
            return f"Error: {str(e)}"


def resolve_biz_params(biz_name: str) -> Dict[str, Any]:
    b = biz_name.strip().upper().replace('-', '_')
    model = os.getenv(f"LLM_MODEL_CONFIG_MODEL_NAME_{b}")
    api_key = os.getenv(f"LLM_MODEL_CONFIG_API_KEY_{b}")
    base_url = os.getenv(f"LLM_MODEL_CONFIG_BASE_URL_{b}")
    temperature = os.getenv(f"LLM_MODEL_CONFIG_TEMPERATURE_{b}")
    max_token = os.getenv(f"LLM_MODEL_CONFIG_MAX_TOKENS_{b}")
    provider = "openrouter"
    model_type = os.getenv(f"LLM_MODEL_CONFIG_MODEL_TYPE_{b}", "CHAT")

    # 设置默认值，确保不返回 None
    if not model:
        model = os.getenv("DEFAULT_MODEL", "openai/gpt-4o-mini")
    if not api_key:
        api_key = os.getenv("DEFAULT_API_KEY")
    if not base_url:
        base_url = os.getenv("DEFAULT_BASE_URL", "https://openrouter.ai/api/v1")
    result = {
        "provider": provider,
        "model": model,
        "api_key": api_key,
        "base_url": base_url,
        "model_type": model_type
    }
    if temperature:
        result.update({"temperature": temperature})
    if max_token:
        result.update({"max_tokens": max_token})
    return result


def _create_openrouter_llm(model: str, api_key: str, base_url: str, temperature: float, max_tokens: int,
                           **kwargs) -> ChatOpenAI:
    # 确保关键参数不为 None
    if not api_key:
        raise ValueError("API key is required but not provided in DEFAULT_API_KEY environment variable")
    if not base_url:
        base_url = "https://openrouter.ai/api/v1"
    if not model:
        model = "openai/gpt-4o-mini"

    config = {
        "model": model,
        "api_key": api_key,
        "base_url": base_url
    }
    if temperature:
        config.update({"temperature": float(temperature)})
    if max_tokens:
        config.update({"max_tokens": int(max_tokens)})
    if kwargs:
        config.update(kwargs)
    return ChatOpenAI(**config)


def create_llm_by_biz(biz_name: str, **overrides) -> ChatOpenAI | OpenRouterImageClient | QunarImageModel:
    params = resolve_biz_params(biz_name)
    model = overrides.pop("model", params.get("model"))
    temperature = overrides.pop("temperature", params.get("temperature"))
    max_tokens = overrides.pop("max_tokens", params.get("max_tokens"))
    api_key = overrides.pop("api_key", params.get("api_key"))
    base_url = overrides.pop("base_url", params.get("base_url"))
    model_type = overrides.pop("model_type", params.get("model_type"))
    # 1. 如果是生图需求，返回自定义的 Runnable 类
    if model_type.upper() == "IMAGE":
        return OpenRouterImageModel(
            model=model,
            api_key=api_key,
            base_url=base_url,
            # 将 temperature 等参数透传给 kwargs
            temperature=temperature,
            max_tokens=max_tokens
        )
    # 2. 如果是去哪儿图生图需求，返回 QunarImageModel
    elif model_type.upper() == "QUNAR_IMAGE":
        return QunarImageModel(
            model=model,
            **overrides  # 将所有额外参数传递给 QunarImageModel
        )
    elif model_type.upper() == "THINKING":
        return _create_openrouter_llm(
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
            api_key=api_key,
            base_url=base_url,
            frequency_penalty=0,
            presence_penalty=0
        )
    # 4. 如果是普通对话，返回 LangChain 标准类
    else:
        return _create_openrouter_llm(
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
            api_key=api_key,
            base_url=base_url,
            **overrides
        )


async def select_node():
    messages = [
        SystemMessage(content="You are a helpful assistant."),
        HumanMessage(content="你好，回答我你是谁。"),
    ]
    llm = create_llm_by_biz("select_node")
    resp = await llm.ainvoke(messages)
    print(resp.content)


def select_node_sync():
    messages = [
        SystemMessage(content="You are a helpful assistant."),
        HumanMessage(content="你好，回答我你是谁。"),
    ]
    llm = create_llm_by_biz("select_node")
    resp = llm.invoke(messages)
    print(resp.content)


if __name__ == "__main__":
    asyncio.run(select_node())
