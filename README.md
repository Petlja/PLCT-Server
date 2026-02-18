# PLCT Server with AI Assistant

PLCT (Petlja Learning Content Tools) Server is a simple server designed to:
- serve learning content built using [PLCT](https://github.com/Petlja/PLCT-CLI) and [PetljaDoc](https://github.com/Petlja/PetljaDoc)
- implement AI Assistant with context data from that learning content

PLCT content is basically static HTML5, but some features of PLCT components may be limited without server-side support. PLCT Server aims to provide the reference PLCT platform implementation suitable for development, demonstration, and simple production scenarios. PCLT Server is an OSS product designed to be easily adapted/integrated to meet specific needs.

> **New here?** See the [Getting Started](doc/getting_started.md) guide for a complete, step-by-step walkthrough — from creating a deployment project to serving courses with an AI Assistant.

## Prerequisites

- Python 3.10+
- The [uv tool](https://docs.astral.sh/uv/) (recommended) or pip
- An OpenAI API key **or** an Azure OpenAI deployment

## Install

### Clone from GitHub

Clone this repo:

```bash
git clone https://github.com/Petlja/PLCT-Server.git
```

### In-place installation

Navigate to the cloned repo:

```bash
cd PLCT-Server
```

Install with uv (recommended):

```bash
uv sync
```

Or install with pip (requires an activated virtual environment):

```bash
pip install -e .
```

### Installation inside another project

Install PLCT Server into your project as a dependency:

**Option 1 — pip:** From your project's activated virtual environment:

```bash
pip install git+https://github.com/Petlja/PLCT-Server.git@v0.3.4
```

**Option 2 — uv (recommended):** Add the dependency to your project's `pyproject.toml`:

```toml
[project]
# ... other settings
dependencies = [
    "plct-server",
    # ... other dependencies
]

[tool.uv.sources]
plct-server = { git = "https://github.com/Petlja/PLCT-Server.git", tag = "v0.3.4" }
```

Then run:

```bash
uv sync
```

Depending on how you have installed Python and configured active python environment, you may use alternative syntax to run the package installation.

## Running PLCT Server

You can run the PLCT Server either locally from command line (using an embedded web server) or deployed on a regular web server.

Ways to run localy from command line:
- use the `plct-serve` shell command:  
  ```
  plct-serve [OPTIONS] [FOLDERS]
  ```
- use as an extended command of PLCT CLI:  
  ```
  plct serve [OPTIONS] [FOLDERS]
  ```

Read [PLCT Server configuration](doc/config.md) for more details on command line options.

PLCT Server can be [deployed as a FastAPI app](https://fastapi.tiangolo.com/deployment/), or more generally, as a Python ASGI web application that is supported by most web servers and PaaS providers:
- Use an ASGI web server like Uvicorn to run `plct_server.ui_main:app` or `plct_server.rag_main:app`

- embed the PLCT Server into your FastAPI app (source of the `plct_server.main` module may be a starting point)

Whichever method you use to run the PLCT Server, you can configure it using a configuration file. For more details, refer to the [PLCT Server configuration](doc/config.md).


## CLI options and configuration

Most configuration options can be set either on the command line or in a configuration file (YAML). A command line option overrides the same option in a configuration file. For full details, refer to the [PLCT Server configuration](doc/config.md).

### `plct-serve` command

```
plct-serve [OPTIONS] [FOLDERS]
```

| Option | Description |
|--------|-------------|
| `FOLDERS` | Positional args — folders of PLCT projects to serve. Defaults to current directory. |
| `-c`, `--config` | Path to a YAML configuration file |
| `-h`, `--host` | Host to bind to (default: `127.0.0.1`) |
| `-p`, `--port` | Port to bind to (default: `9000`) |
| `-v`, `--verbose` | Enable verbose (debug) logging |
| `-a`, `--ai-context` | Folder or URL with the AI context dataset |
| `-e`, `--azure-ai-endpoint` | Azure OpenAI endpoint. Use `modelname=endpoint` syntax for model-specific values |

### Configuration file

Specify the configuration file via `-c` option or the `PLCT_SERVER_CONFIG_FILE` environment variable. Available keys:

```yaml
verbose: false
content_url: ../courses            # base URL for course_paths
course_paths:                       # list of PLCT project paths
  - intro_to_prog
  - databases
ai_ctx_url: ai-context              # AI context dataset path or URL
api_key: <your-api-key>             # API key for RAG REST API access
azure_default_ai_endpoint: https://my-endpoint.openai.azure.com/
vllm_url: http://localhost:8000/v1  # vLLM server URL
```

### Environment variables

| Variable | Description |
|----------|-------------|
| `PLCT_SERVER_CONFIG_FILE` | Path to the YAML configuration file |
| `CHATAI_OPENAI_API_KEY` | OpenAI API key |
| `CHATAI_AZURE_API_KEY` | Azure OpenAI Service API key |
| `CHATAI_VLLM_API_KEY` | vLLM server API key |
| `PLCT_API_KEY` | API key for RAG REST API access |

## Setting up development environment

You need to have installed Git, Python, uv and Node.js/npm. If you don't have experience with all those tools, take a look at how to use them.

Clone the repo into your local project folder.

Create a Python virtual environment for the project and make it active. You may use uv to create the virtual environment (`uv venv`), but you also can keep using whatever you want since uv works well in any active Python virtual environment.

Take care to have the Python virtual environment activated before continue. If you use terminal/console integrated in your IDE, set it up to have an appropriate virtual environment activated.

Do initial install/build using npm:

```
pushd front-app
npm install
npm run build
popd
uv sync
```

It's also okay if you have done `uv sync` previously.

## Run server in the development environment

You can run the PLCT Server using `plct-serve` command as it is explained in the Usage section above, since the `uv sync` command makes dev install of the package you are developing (like `pip -e .`).

When using the `plct-serve` command during development, you'll need to restart the server for any changes to take effect. Additionally, when you make changes to the React front-end, you need to execute `npm install`.

You can ran the dev-mode server on `http://localhost:9000` using the `dev-server.cmd` or `dev-server.sh` script (depending on your OS). When run this way, the server will do live-reload on any change in the `plct_server` package.

The *dev-server* script does't support arguments, but you may edit the `plct-server-config.yaml` file instead. When you run the *dev-server* script first time, the `plct-server-config.yaml` file will be created as a copy of `plct-server-config-sample.yaml`. For more details on config options, refer to the [PLCT Server configuration](doc/config.md).

If you also require live reload for the React front-end, you can run the front-end server on `http://localhost:3000` by using the `npm start` command in the `front-app` folder.

Through the front-end URL, you have full access to the PLCT Server because the front-end server forwards all non-front-end requests to `http://localhost:9000`.

By using both the dev-mode server and the front-end server, you can achieve live reload for both the front-end and back-end changes.

## What is inside

The `plct_server` folder the Python package with a FastAPI based server and the `front-app` folder contains a React front-end. 

The `npm run build` command copies the `front-app\build` folder into `plct_server\front-app\build`. So, the FastAPI server serves both minimized bundles of the React front-end and the back-end API. FastAPI also serves some other web pages beyond th React front-end. 

Thus, the architecture combines a single-page application (SPA) and server-side rendering within a single server, while maintaining simplicity from the end-user's perspective.

## Batch Review Command

You can use the `batch-review` command to review conversation in batches. This command helps in comparing the performance of the AI assistant between updates. The report will be generated in an html file where you can compare and evaluate the difference in the answers you get to the same `conversation`.

### What is a Conversation?

`Conversation` is a snapshot of an interaction between a user and the AI assistant. Here is an example of a conversation instance: 


```json
[
    {
        "history": [
            [
                "History item #1",
                "History item #2"
            ],
            [
                "History item #3",
                "History item #4"
            ]
        ],
        "query": "User query",
        "response": "",
        "benchmark_response": "Benchmark response",
        "course_key": "course_key",
        "activity_key": "activity_key",
        "feedback": 0,
        "model": "gpt-4o"
    }
]

```

Ways to run the command:
- use the `plct-serve` shell command:  
  ```
  plct-batch-review [OPTIONS]
  ```
- use as an extended command of PLCT CLI:  
  ```
  plct batch-review [OPTIONS]
  ```


**OPTIONS:**
- `-a`, `--ai-context`: Folder with AI context
- `-n`, `--batch-name`: Batch name (default: a newly generated UUID)
- `-b`, `--set-benchmark`: Set responses as the benchmark responses
- `-v`, `--verbose`: Enable verbose logging
- `-c`, `--compare-with-ai`: Compare responses with AI
- `-d`, `--conversation-dir`: Directory holding pre-arranged conversations (default: `eval/conversations/default`)
- `-m`, `--model` : Model to be used in every conversation instance. If not given the conversations will be done by the default model or the model defined in the conversation instance
- `-nr`, `--no-report` : Optionally you can disable the creation of the report

**Example:**

```
plct batch-review -n test -v
```


This command will configure the server, run the batch prompts for conversations and generate an HTML report(`eval/result`) comparing the responses.

The default conversations can be found in `eval/conversations/default`. You can group sets of conversations into a single JSON file or split them into multiple files within the same directory.