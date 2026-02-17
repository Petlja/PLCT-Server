# PLCT Server Configuration

Most configuration options can be set either on the command line or in a configuration file, while some are configured using environment variables.

A command line option overrides the same option configured in a configuration file.

The configuration file is a YAML file where each key represents an option.

## Specifying the configuration file

There is no default configuration file. If you need a configuration file, you can specify it either via the command line or by setting an environment variable.

### command line

Use `-c` or `--config` with a file name in the argument. Example:
```
plct-serve -c plct-server-config.yaml
```

### environment variable

Use the `PLCT_SERVER_CONFIG_FILE` environment variable.

You don’t need to use the `plct-server` command line; instead, you can run the PLCT Server like any Python ASGI web application. In this case, you can use the `PLCT_SERVER_CONFIG_FILE` environment variable along with the appropriate configuration file to set the options. For example, you can run the PLCT Server using the Uvicorn ASGI web server:

*Windows Command Prompt*
```
SET PLCT_SERVER_CONFIG_FILE=plct-server-config.yaml
uvicorn plct_server.ui_main:app --host 127.0.0.1 --port 9000
```
*Bash shell*
```
export PLCT_SERVER_CONFIG_FILE=plct-server-config.yaml
uvicorn plct_server.ui_main:app --host 127.0.0.1 --port 9000
```


## Verbose messages

You can configure verbose messages, which will effectively set the debug log level.

### cmmand line

Use `-v` or `--verbose`. Example:
```
plct-serve -v
```

### configuration file

Use `verbose` key with `true` value. Example:

```yaml
verbose: true
```

## Paths to PLCT courses to be served
### command line
Use positional command line arguments to specify the folder paths of PLCT projects. Example:

```
plct-serve ../courses/intro_to_prog ../courses/databases
```

Relative paths are considered relative to the current folder.

### configuration file<a id='course_paths'></a>

Use the `course_paths` key. Example:
```yaml
course_paths:
  - ../courses/intro_to_prog
  - ../courses/databases
```
Relative paths are interpreted as follows:
- If [`content_url`](#content_url) is **not configured**, they are considered relative to the folder of the configuration file.
- If [`content_url`](#content_url) is **configured**, they are considered relative to the [`content_url`](#content_url). However, if [`content_url`](#content_url) is itself a relative path, it is considered relative to the folder of the configuration file.


## Base URL for PLCT courses
### command line
The command line option is not implemented yet.
### configuration file<a id='content_url'></a>

Use the `content_url` key. It is intended for use in conjunction with [`course_paths`](#course_paths). Example:

```yaml
content_url: ../courses
course_paths:
  - intro_to_prog
  - databases
```
## Host and port

### command line

You may configure host and port the HTTP service should be bind to.

Use `-h` or `--host` option to set the host and `-p` or `--port` option to set the port. Example:
```
plct-serve -h 127.0.0.1 -p 9000
```

### configuration file

Host and port options cannot be configured in a configuration file. These options are specific to the `plct-serve` command that embeds an HTTP server.

## AI context dataset
AI Assistant implementation uses a preprocessed context dataset that you can create using a Python script with the `ContextDatasetBuilder` class from the [`plct_server.ai.context_dataset`](https://github.com/Petlja/PLCT-Server/blob/main/plct_server/ai/context_dataset.py) module.

Context dataset is a file-set that can be accessed either locally or via HTTP(S).

### command line

Use `-a` or `--ai-context` with a folder URL. Example:
```
plct-serve --ai-context ../ai_assistant_scripts/ai-context
```

Relative patsh are considered relative to the current folder. Supported URL schemes are `http`, `https` and `file`.

### configuration file

Use the `ai_ctx_url` key. Example:

```yaml
ai_ctx_url: ../ai_assistant_scripts/ai-context
```

Relative paths are considered relative to the folder of the configuration file. Supported URL schemes are `http`, `https` and `file`.

## RAG API key

PLCT server implements the Retrieval Augmented Generation (RAG) REST API. To enable access to the API, you need to specify an API key.

### configuration file

Use the `api_key` key. Example:

```yaml
api_key: 695613bb32c64842bd64aff8f8edc51951a90a183ff3b690697f0247657deb48
```

The API key in the above example is randomly generated SHA-256 hash.

### environment variables

Use the `PLCT_API_KEY` environment variable to set your api key.

## OpenAI API keys

### environment variables

Use the `CHATAI_OPENAI_API_KEY` environment variable to set the OpenAI API key or use
`CHATAI_AZURE_API_KEY` to set Azure OpenAI Service key and if you do make sure you set the `azure_default_ai_endpoint`.

## Azure OpenAI Service

By default, the PLCT server uses the standard OpenAI endpoint, but it can also be configured to use Azure OpenAI Service endpoints. Different Azure OpenAI Service endpoints may be configured for different models.

### command line

Use `-e`, `--azure-ai-endpoint` to set the endpoint. Example:

```
plct-serve -e https://my_endpoint1.openai.azure.com/
```

### configuration file

Use the `azure_default_ai_endpoint` string for default Azure OpenAI Service. Example:

```yaml
azure_default_ai_endpoint: https://my_endpoint1.openai.azure.com/
```

Once the Azure OpenAI Service endpoint is provided, ensure that you set up your Azure environment with the correct models. This includes specifying the model names, deployment names, and API versions that you will use. You can modify or reference the `MODEL_CONFIGS`, located in the PLCT Server configuration module [`plct_server.ai.conf`](https://github.com/Petlja/PLCT-Server/blob/main/plct_server/ai/conf.py)


```python
MODEL_CONFIGS = {
    "gpt-4o-mini": ModelConfig(
        name="gpt-4o-mini",
        azure_deployment_name="gpt-4o-mini",
        api_version="2023-03-15-preview",
        type="chat",
        context_size=128_000
    ),
    "gpt-4o": ModelConfig(
        name="gpt-4o",
        azure_deployment_name="gpt-4o"
        api_version="2024-02-15-preview",
        type="chat",
        context_size=128_000
    ),
    "text-embedding-3-large": ModelConfig(
        name="text-embedding-3-large",
        azure_deployment_name="text-embedding-3-large",
        api_version="2023-05-15",
        type="embedding",
        context_size=8_191
    )
}
```

For example, if you already have an Azure OpenAI deployment for the gpt-4o-mini model named `my-gpt-4o-mini`, ensure that the azure_deployment_name and api_version fields are correctly configured:

```python
  azure_deployment_name="my-gpt-4o-mini"
  api_version="2023-05-15"
```













