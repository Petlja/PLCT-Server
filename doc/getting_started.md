# Getting Started — PLCT Server with AI Assistant

This guide walks you through the full deployment of PLCT Server with an AI Assistant, from setting up a project directory to serving courses with AI-powered context. By the end you will have a working deployment project that references PLCT-Server and PLCT-AI-Ctx as dependencies and serves PLCT courses with an integrated AI Assistant.

## Overview

A typical deployment brings together three repositories and one or more PLCT course projects:

| Component | Purpose |
|-----------|---------|
| [PLCT-Server](https://github.com/Petlja/PLCT-Server) | FastAPI server — serves PLCT courses and the AI Assistant |
| [PLCT-AI-Ctx](https://github.com/Petlja/PLCT-AI-Ctx) | Builds the AI context dataset (summaries, embeddings) from course content |
| Your deployment project (e.g. `My-PLCT-Deployment`) | Ties everything together — holds configuration, courses, and the generated AI context |

The deployment process has four main stages:

1. **Set up** the deployment project and install dependencies
2. **Select and set up** the courses to serve
3. **Build** the AI context dataset from your courses
4. **Run** the PLCT Server

## Prerequisites

- The [uv tool](https://docs.astral.sh/uv/) 
- Git
- An OpenAI API key **or** an Azure OpenAI deployment

This guide uses `uv run ...` to run commands inside a Python virtual environment, letting `uv` manage the environment, dependency installation, and even Python itself. You may adapt the commands to your own workflow if preferred.

## Directory Layout

Clone the PLCT-Server and PLCT-AI-Ctx repositories into the same parent directory and create your deployment project folder:

```bash
git clone https://github.com/Petlja/PLCT-Server.git
git clone https://github.com/Petlja/PLCT-AI-Ctx.git
mkdir My-PLCT-Deployment
```

Your directory layout should look like:

```
parent-dir/
├── PLCT-Server/
├── PLCT-AI-Ctx/
└── My-PLCT-Deployment/       # your deployment project
```

Course projects will be cloned inside the deployment project in Step 2.

The rest of this guide assumes you are working inside the `My-PLCT-Deployment` directory.

## Step 1 — Initialize the Deployment Project

Navigate to the deployment project directory:

```bash
cd My-PLCT-Deployment
```

### Create `pyproject.toml`

Create a `pyproject.toml` that declares both PLCT-Server and PLCT-AI-Ctx as local, editable dependencies:

```toml
[project]
name = "my-plct-deployment"
version = "0.1.0"
requires-python = ">=3.10"
dependencies = [
    "plct-server",
    "plct-ai-ctx",
]

[tool.uv.sources]
plct-server = { path = "../PLCT-Server", editable = true }
plct-ai-ctx = { path = "../PLCT-AI-Ctx", editable = true }
```

### Install dependencies

Dependencies are installed automatically on the first `uv run` command, but it is a good idea to run `uv sync` now to verify that everything resolves correctly:

```bash
uv sync
```

### Create `.gitignore`

Courses, generated context data, and virtual environments should not be committed. Create a `.gitignore`:

```gitignore
__pycache__/
*.py[cod]
.venv/
uv.lock
courses
summaries
ai-context
```

Add other entries as needed for your project or tools you use.

## Step 2 — Select and Set Up Courses

PLCT and PetljaDoc courses are cloned and built inside the `courses/` subdirectory of your deployment project. Each course must be built before the server can serve it.

Create a `courses` directory and clone the courses you want to serve. Some courses use [PetljaDoc](https://github.com/Petlja/PetljaDoc) (`petljadoc publish`) and some use the newer [PLCT-CLI](https://github.com/Petlja/PLCT-CLI) (`plct build`).

### Example — setting up courses

```bash
mkdir courses
cd courses

# PetljaDoc courses — clone and build with petljadoc
git clone https://github.com/Petlja/os6_inf_ikt
uv run --directory os6_inf_ikt petljadoc publish

git clone https://github.com/Petlja/os6_inf_prog
uv run --directory os6_inf_prog petljadoc publish

git clone https://github.com/Petlja/specit1_prog
uv run --directory specit1_prog petljadoc publish

# PLCT-CLI courses — clone and build with plct
git clone https://github.com/Petlja/TextualProgrammingInPython
uv run --directory TextualProgrammingInPython plct build

cd ..
```

After this step your directory should look like:

```
My-PLCT-Deployment/
├── pyproject.toml
├── .gitignore
└── courses/
    ├── os6_inf_ikt/
    ├── os6_inf_prog/
    ├── specit1_prog/
    └── TextualProgrammingInPython/
```

You can find many more PLCT/PetljaDoc courses at `https://github.com/Petlja/`.

## Step 3 — Configure API Keys

Set the required environment variable(s) for your AI provider. Even if you plan to use vLLM for inference (see Step 6), an OpenAI or Azure OpenAI key is needed for context preparation and parts of the RAG pipeline.

**OpenAI:**

*Bash*
```bash
export CHATAI_OPENAI_API_KEY="sk-..."
```

*PowerShell*
```powershell
$env:CHATAI_OPENAI_API_KEY = "sk-..."
```

**Azure OpenAI Service:**

*Bash*
```bash
export CHATAI_AZURE_API_KEY="..."
```

*PowerShell*
```powershell
$env:CHATAI_AZURE_API_KEY = "..."
```

## Step 4 — Build the AI Context Dataset

The AI Assistant requires a preprocessed context dataset built from your course content. The [PLCT-AI-Ctx](https://github.com/Petlja/PLCT-AI-Ctx) tool handles this.

### Create `plct-ai-ctx-config.yaml`

Create a configuration file in your deployment project directory. The `course_paths` should list the courses you set up in Step 2:

```yaml
course_paths:
  - courses/os6_inf_ikt
  - courses/os6_inf_prog
  - courses/specit1_prog
  - courses/TextualProgrammingInPython
embedding_sizes:
  - 256
  - 1536
embedding_model: "text-embedding-3-large"
chunk_size: 3072
chunk_overlap: 1524
base_dir: "ai-context"

# Optional — omit for direct OpenAI usage
# azure_endpoint: "https://<resource>.openai.azure.com"
# azure_api_version: "2023-03-15-preview"
# azure_embedding_api_version: "2023-05-15"
```

Each path in `course_paths` should point to a PLCT course project built with [PLCT-CLI](https://github.com/Petlja/PLCT-CLI) or [PetljaDoc](https://github.com/Petlja/PetljaDoc).

### Run the context build

```bash
uv run plct-ai-ctx-build
```

This will:

1. Generate per-activity summaries for each course
2. Create consolidated and short course summaries
3. Split content into token-sized chunks and compute embeddings
4. Write the context dataset to the `ai-context/` directory

After the build completes, your project directory will contain:

```
My-PLCT-Deployment/
├── pyproject.toml
├── plct-ai-ctx-config.yaml
├── ai-context/
│   ├── chunks/                    # content-addressed text chunks with embeddings
│   ├── os6_inf_ikt/               # course-level summary metadata
│   ├── os6_inf_prog/
│   ├── specit1_prog/
│   └── TextualProgrammingInPython/
├── courses/
│   └── ...
└── summaries/
    ├── os6_inf_ikt/               # per-activity summaries
    ├── os6_inf_prog/
    ├── specit1_prog/
    └── TextualProgrammingInPython/
```

### CLI Options

| Flag | Description |
|------|-------------|
| `--force_activity_summary` | Regenerate all per-activity summaries even if they already exist |
| `--force_course_summary` | Regenerate the short course summary even if it already exists |
| `--delete_inactive_chunks` | Remove chunks from the index that are no longer referenced |

Example — full rebuild:

```bash
uv run plct-ai-ctx-build --force_activity_summary --force_course_summary
```

## Step 5 — Configure the PLCT Server

### Create `plct-server-config.yaml`

Create a server configuration file in your deployment project directory. The `course_paths` should match the courses you set up in Step 2:

```yaml
course_paths:
  - courses/os6_inf_ikt
  - courses/os6_inf_prog
  - courses/specit1_prog
  - courses/TextualProgrammingInPython
ai_ctx_url: ai-context

# Optional — uncomment for Azure OpenAI
# azure_default_ai_endpoint: https://<resource>.openai.azure.com/

# Optional — uncomment to use a vLLM server for inference
# vllm_url: http://localhost:8000/v1
```

For a full reference of all configuration options, see [PLCT Server Configuration](config.md).

### Key configuration options

| Key | Description |
|-----|-------------|
| `course_paths` | List of paths to PLCT course projects to serve |
| `content_url` | Base URL for `course_paths` (paths become relative to it) |
| `ai_ctx_url` | Path or URL to the AI context dataset |
| `api_key` | API key for RAG REST API access |
| `azure_default_ai_endpoint` | Azure OpenAI Service endpoint |
| `vllm_url` | vLLM server URL for local model serving |

## Step 6 — Using vLLM for Inference (Optional)

PLCT Server can use a [vLLM](https://docs.vllm.ai/) server as a model provider for chat inference, letting you serve open-weight models (e.g. Llama, Qwen) on your own infrastructure. OpenAI or Azure OpenAI API keys are still required for AI context preparation (embeddings, summaries) and for certain RAG phases — vLLM replaces only the final chat model.

### Start a vLLM server

vLLM requires a Linux machine with a supported GPU. Install and launch it following the [vLLM documentation](https://docs.vllm.ai/). For instance, run:

```bash
vllm serve Qwen/Qwen3-32B --reasoning-parser qwen3
```

This starts an OpenAI-compatible API on `http://localhost:8000/v1`.

### Connect PLCT Server to vLLM

Add the `vllm_url` key to your `plct-server-config.yaml`, for instance:

```yaml
vllm_url: http://localhost:8000/v1
```

If the vLLM server requires an API key, set `CHATAI_VLLM_API_KEY` (defaults to `EMPTY` if not set).

PLCT Server queries the vLLM endpoint at startup and automatically registers any served models. To customize options like `context_size` or stop tokens, see the [vLLM Server](config.md#vllm-server) section in the configuration reference.

### Remote vLLM server

When vLLM runs on a remote GPU machine that is not directly reachable from the PLCT Server host, you may use an SSH tunnel to forward the port:

```bash
ssh -L 8000:localhost:8000 user@gpu-server
```

Once connected, start `vllm serve` in the SSH session on the remote machine. The tunnel forwards the remote port to your local machine, so you can use `vllm_url: http://localhost:8000/v1` in your config as usual.

## Step 7 — Run the Server

### Using `plct-serve` command

```bash
uv run plct-serve
```

The server starts on `http://127.0.0.1:9000` by default and loads `plct-server-config.yaml` from the current directory.

Common options:

```bash
# Explicit config file
uv run plct-serve -c my-config.yaml

# Custom host and port
uv run plct-serve -h 0.0.0.0 -p 8080

# Verbose logging
uv run plct-serve -v

# Override AI context location
uv run plct-serve -a ./ai-context
```

### Using the configuration file environment variable

You can also specify the configuration file by setting the `PLCT_SERVER_CONFIG_FILE` environment variable:

*Bash*
```bash
export PLCT_SERVER_CONFIG_FILE=plct-server-config.yaml
uv run plct-serve
```

*Windows PowerShell*
```powershell
$env:PLCT_SERVER_CONFIG_FILE = "plct-server-config.yaml"
uv run plct-serve
```

### Using Uvicorn directly

You can also run the server as a standard ASGI application:

```bash
export PLCT_SERVER_CONFIG_FILE=plct-server-config.yaml
uv run uvicorn plct_server.ui_main:app --host 127.0.0.1 --port 9000
```

Use `plct_server.ui_main:app` for the full UI + API, or `plct_server.rag_main:app` for the RAG API only.

## Final Project Structure

After completing all steps, your deployment project should look like this:

```
My-PLCT-Deployment/
├── pyproject.toml
├── .gitignore
├── set-up-courses.bat
├── plct-ai-ctx-config.yaml
├── plct-server-config.yaml
├── courses/
│   ├── os6_inf_ikt/
│   ├── os6_inf_prog/
│   ├── specit1_prog/
│   └── TextualProgrammingInPython/
├── ai-context/
│   ├── chunks/
│   ├── os6_inf_ikt/
│   ├── os6_inf_prog/
│   ├── specit1_prog/
│   └── TextualProgrammingInPython/
└── summaries/
    ├── os6_inf_ikt/
    ├── os6_inf_prog/
    ├── specit1_prog/
    └── TextualProgrammingInPython/
```

## Environment Variables Reference

| Variable | Description |
|----------|-------------|
| `PLCT_SERVER_CONFIG_FILE` | Path to the server YAML configuration file |
| `CHATAI_OPENAI_API_KEY` | OpenAI API key |
| `CHATAI_AZURE_API_KEY` | Azure OpenAI Service API key |
| `CHATAI_VLLM_API_KEY` | vLLM server API key |
| `PLCT_API_KEY` | API key for RAG REST API access |

## Troubleshooting

### Server starts but AI Assistant does not respond

- Verify that `ai_ctx_url` in your server config points to the correct `ai-context/` directory
- Check that the API key environment variable is set (`CHATAI_OPENAI_API_KEY` or `CHATAI_AZURE_API_KEY`)
- Run with `-v` flag for verbose logging

### Context build fails

- Ensure all paths in `course_paths` in `plct-ai-ctx-config.yaml` point to valid PLCT course projects
- Verify that the API key environment variable is set
- For Azure OpenAI, check that the endpoint and API version are correct

### Courses not showing up

- Verify that `course_paths` in `plct-server-config.yaml` point to valid, built PLCT course projects
- If using `content_url`, ensure relative paths in `course_paths` are relative to it