from pydantic import BaseModel
from enum import Enum

class ModelProvider(Enum):
    OPENAI = "openai"
    AZURE = "azure"
    VLLM = "vllm"

class ModelConfig(BaseModel):
    name: str
    display_name: str | None = None
    azure_deployment_name: str = ""
    azure_api_version: str = ""
    context_size: int
    type : str
    extra_body : dict = {}
    provider : ModelProvider | None = None  # use default provider if None
    order: int = 0  # for sorting models in the UI
    encoding: str | None = None
    supports_tools: bool = True

MODEL_CONFIGS_LIST = [
    ModelConfig(
        name="gpt-4o-mini",
        provider = None,  # use default provider
        azure_deployment_name="gpt-4o-mini",
        azure_api_version="2023-03-15-preview",
        type = "chat",
        context_size=128_000,
        encoding="o200k_base"
    ),
    ModelConfig(
        name="gpt-4o",
        provider = None,  # use default provider
        azure_deployment_name="gpt-4o",
        azure_api_version="2024-02-15-preview",
        type = "chat",
        context_size=128_000,
        encoding="o200k_base"
    ),
    ModelConfig(
        name="text-embedding-3-large",
        provider = None,  # use default provider
        azure_deployment_name="text-embedding-3-large",
        azure_api_version="2023-05-15",
        type = "embedding",
        context_size=8_191,
        encoding="cl100k_base"
    ),
    ModelConfig(
        name="text-embedding-3-small",
        provider = None,  # use default provider
        azure_deployment_name="text-embedding-3-small",
        azure_api_version="2023-05-15",
        type = "embedding",
        context_size=8_191,
        encoding="cl100k_base"
    ),
    ModelConfig(
        name="gpt-5.2",
        provider = ModelProvider.OPENAI,
        type = "chat",
        context_size=128_000,
        encoding="o200k_base"
    ),
    ModelConfig(
        name="meta-llama/Llama-3.1-70B-Instruct",
        provider = ModelProvider.VLLM,
        type = "chat",
        context_size=128_000,
        extra_body = {
                "stop_token_ids": [128001,128008,128009]
            }
    ),
    ModelConfig(
        name="nvidia/Llama-3.3-70B-Instruct-FP8",
        provider = ModelProvider.VLLM,
        type = "chat",
        context_size=98_304
    ),
    ModelConfig(
        name="Qwen/Qwen3-32B",
        provider= ModelProvider.VLLM,
        type = "chat",
        context_size=32_768
    ),
    ModelConfig(
        name="Qwen/Qwen3-14B",
        provider= ModelProvider.VLLM,
        type = "chat",
        context_size=32_768
    ),
    ModelConfig(
        name="Qwen/Qwen3-8B",
        provider = ModelProvider.VLLM,
        type = "chat",
        context_size=32_768
    ),
    ModelConfig(
        # vLLM reports a 262144 max model len for this one, but it is compared
        # head-to-head against the Qwen entries above, so it gets their context
        # size rather than an advantage none of the test cases need.
        name="mistralai/Ministral-3-14B-Instruct-2512-BF16",
        provider = ModelProvider.VLLM,
        type = "chat",
        context_size=32_768
    )

]