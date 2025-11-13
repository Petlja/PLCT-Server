from pydantic import BaseModel
from enum import Enum

class ModelProvider(Enum):
    OPENAI = "openai"
    AZURE = "azure"

class ModelConfig(BaseModel):
    name: str
    azure_deployment_name: str
    azure_api_version: str
    context_size: int
    type : str
    extra_body : dict = {}

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
        azure_deployment_name="", 
        azure_api_version="",
        type = "chat",
        context_size=128_000,
        extra_body = {
                "stop_token_ids": [128001,128008,128009]
            }
    )
}