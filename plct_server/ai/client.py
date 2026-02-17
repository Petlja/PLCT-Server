import logging

from typing import Union
from openai import AsyncAzureOpenAI, AsyncOpenAI, OpenAI
from .model_conf import ModelConfig, ModelProvider

logger = logging.getLogger(__name__)

class AiClientFactory:
    def __init__(self, 
                 default_provider: ModelProvider, 
                 openai_api_key: str, 
                 azure_api_key: str,
                 vllm_api_key: str,
                 vllm_url: str = None,
                 azure_default_ai_endpoint: str = None):
        logger.debug(f"Creating AiClientFactory with provider {default_provider}")
        self.default_provider = default_provider
        self.openai_api_key = openai_api_key
        self.azure_api_key = azure_api_key
        self.vllm_api_key = vllm_api_key or "EMPTY"
        self.vllm_url = vllm_url
        self.azure_default_ai_endpoint = azure_default_ai_endpoint
        

    def get_client(self, model_config: ModelConfig) -> Union[AsyncOpenAI, AsyncAzureOpenAI]:
        provider = model_config.provider or self.default_provider
        if provider == ModelProvider.VLLM:
            logger.debug(f"Using local VLLM server for model {model_config.name}")
            return AsyncOpenAI(api_key=self.vllm_api_key, base_url=self.vllm_url)
        if provider == ModelProvider.OPENAI:
            logger.debug(f"Using OpenAI API with model {model_config.name}")
            return AsyncOpenAI(api_key=self.openai_api_key)
        if provider == ModelProvider.AZURE:
            logger.debug(f"Using Azure API with model {model_config.name} and endpoint {self.azure_default_ai_endpoint}")
            return AsyncAzureOpenAI(
                api_key=self.azure_api_key,
                azure_endpoint=self.azure_default_ai_endpoint,
                azure_deployment=model_config.azure_deployment_name,
                api_version=model_config.azure_api_version
            )
        raise ValueError(f"Unsupported AI provider: {provider}")

    def list_vllm_models(self) -> dict[str, int]:
        """Query the vLLM server for available models using the OpenAI-compatible API.
        
        Returns a dict mapping model id to max_model_len, e.g.:
            {"Qwen/Qwen3-8B": 32768, ...}
        """
        if not self.vllm_url:
            return {}
        try:
            client = OpenAI(api_key=self.vllm_api_key, base_url=self.vllm_url)
            models = client.models.list()
            result = {}
            for model in models.data:
                # vLLM extends the OpenAI response with max_model_len
                max_model_len = getattr(model, "max_model_len", None)
                if max_model_len is None and hasattr(model, "model_extra"):
                    max_model_len = (model.model_extra or {}).get("max_model_len")
                result[model.id] = int(max_model_len) if max_model_len is not None else 0
            return result
        except Exception as e:
            logger.error(f"Failed to list vLLM models: {e}")
            return {}