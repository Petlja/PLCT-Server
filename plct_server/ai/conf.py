from pydantic import BaseModel

AZURE_ENDPOINT = "https://petljaopenaiservicev2.openai.azure.com/"

class ModelConfig(BaseModel):
    name: str
    azure_deployment_name: str
    azure_endpoint: str
    api_version: str
    context_size: int
    model_type : str

MODEL_CONFIGS = {
    "gpt-4o-mini": ModelConfig(
        name="gpt-4o-mini",
        azure_deployment_name="gpt-4o-mini",
        azure_endpoint=AZURE_ENDPOINT,
        api_version="2023-03-15-preview",
        model_type = "chat",
        context_size=128_000
    ),
    "text-embedding-3-large": ModelConfig(
        name="text-embedding-3-large",
        azure_deployment_name="text-embedding-3-large",
        azure_endpoint=AZURE_ENDPOINT,
        api_version="2023-05-15",
        model_type = "embedding",
        context_size=8_191
    ),
    "gpt-4o": ModelConfig(
        name="gpt-4o",
        azure_deployment_name="gpt-4o",
        azure_endpoint=AZURE_ENDPOINT,
        api_version="2024-02-15-preview",
        model_type = "chat",
        context_size=128_000
    )
}