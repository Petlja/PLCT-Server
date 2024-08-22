AZURE_ENDPOINT = "https://petljaopenaiservicev2.openai.azure.com/"

MODEL_CONFIGS = {
    "gpt-4o-mini": {
        "LLM_MODEL": "gpt-4o-mini",
        "AZURE_DEPLOYMENT_NAME": "gpt-4o-mini",
        "AZURE_ENDPOINT": AZURE_ENDPOINT,
        "API_VERSION": "2023-03-15-preview",
        "CONTEXT_SIZE": 128_000
    },
    "text-embedding-3-large": {
        "LLM_MODEL": "text-embedding-3-large",
        "AZURE_DEPLOYMENT_NAME": "text-embedding-3-large",
        "AZURE_ENDPOINT": AZURE_ENDPOINT,
        "API_VERSION": "2023-05-15",
        "CONTEXT_SIZE": 8_191
    },
    "gpt-35-turob-16k": {
        "LLM_MODEL": "gpt-35-turob-16k",
        "AZURE_DEPLOYMENT_NAME": "gpt-35-turob-16k",
        "AZURE_ENDPOINT": AZURE_ENDPOINT,
        "API_VERSION": "2023-03-15-preview",
        "CONTEXT_SIZE": 16_385
    }
}