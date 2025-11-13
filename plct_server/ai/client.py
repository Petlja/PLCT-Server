import logging

from typing import Union
from openai import AsyncAzureOpenAI, AsyncOpenAI
from plct_server.ai.conf import ModelConfig, ModelProvider

logger = logging.getLogger(__name__)

class AiClientFactory:
    def __init__(self, provider: ModelProvider, api_key: str, azure_default_ai_endpoint: str = None):
        logger.debug(f"Creating AiClientFactory with provider {provider}")
        self.provider = provider
        self.api_key = api_key
        self.azure_default_ai_endpoint = azure_default_ai_endpoint

    def get_client(self, model_config: ModelConfig) -> Union[AsyncOpenAI, AsyncAzureOpenAI]:
        if model_config.name == "meta-llama/Llama-3.1-70B-Instruct":
            logger.debug(f"Using Llama-3.1-70B model")
            return AsyncOpenAI(api_key="EMPTY", base_url="http://localhost:8000/v1")
        if self.provider == ModelProvider.OPENAI:
            logger.debug(f"Using OpenAI API with key {self.api_key}")
            return AsyncOpenAI(api_key=self.api_key)
        
        elif self.provider == ModelProvider.AZURE:
            logger.debug(f"Using Azure API with model {model_config.name} and endpoint {self.azure_default_ai_endpoint}")
            return AsyncAzureOpenAI(
                api_key=self.api_key,
                azure_endpoint=self.azure_default_ai_endpoint,
                azure_deployment=model_config.azure_deployment_name,
                api_version=model_config.azure_api_version
            )
        
        else:
            raise ValueError(f"Unsupported AI provider: {self.provider}")