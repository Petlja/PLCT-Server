from pydantic import BaseModel
from enum import Enum

class ModelProvider(Enum):
    OPENAI = "openai"
    AZURE = "azure"
    VLLM = "vllm"

class ModelConfig(BaseModel):
    name: str
    azure_deployment_name: str = ""
    azure_api_version: str = ""
    context_size: int
    type : str
    extra_body : dict = {}
    vllm_url : str = None
    provider : ModelProvider = None  # use default provider if None

MODEL_CONFIGS = {
    "gpt-4o-mini": ModelConfig(
        name="gpt-4o-mini",
        azure_deployment_name="gpt-4o-mini",
        azure_api_version="2023-03-15-preview",
        type = "chat",
        context_size=128_000
    ),
    "gpt-4o": ModelConfig(
        name="gpt-4o",
        azure_deployment_name="gpt-4o",
        azure_api_version="2024-02-15-preview",
        type = "chat",
        context_size=128_000
    ),
    "text-embedding-3-large": ModelConfig(
        name="text-embedding-3-large",
        azure_deployment_name="text-embedding-3-large",
        azure_api_version="2023-05-15",
        type = "embedding",
        context_size=8_191
    ),
    "meta-llama/Meta-Llama-3.1-70B" : ModelConfig(
        name="meta-llama/Llama-3.1-70B-Instruct",
        vllm_url = "http://localhost:8000/v1",
        provider = ModelProvider.VLLM,
        type = "chat",
        context_size=128_000,
        extra_body = {
                "stop_token_ids": [128001,128008,128009]
            }
    ),

    "nvidia/Llama-3.3-70B-Instruct-FP8" : ModelConfig(
        name="nvidia/Llama-3.3-70B-Instruct-FP8",
        vllm_url = "http://localhost:8000/v1",
        provider = ModelProvider.VLLM,
        type = "chat",
        context_size=98_304
    ),

    "Qwen/Qwen3-32B" : ModelConfig(
        name="Qwen/Qwen3-32B",
        vllm_url = "http://localhost:8000/v1",
        provider= ModelProvider.VLLM,
        type = "chat",
        context_size=32_768
    ),
    "Qwen/Qwen3-14B" : ModelConfig(
        name="Qwen/Qwen3-14B",
        vllm_url = "http://localhost:8000/v1",
        provider= ModelProvider.VLLM,
        type = "chat",
        context_size=32_768
    ),
    "Qwen/Qwen3-8B" : ModelConfig(
        name="Qwen/Qwen3-8B",
        vllm_url = "http://localhost:8000/v1",
        provider = ModelProvider.VLLM,
        type = "chat",
        context_size=32_768
    )
    
}