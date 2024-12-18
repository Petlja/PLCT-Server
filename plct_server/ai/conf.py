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
    )
}