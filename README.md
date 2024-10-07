# PLCT Server

*This project is in the proof-of-concept stage.*

PLCT (Petlja Learning Content Tools) Server is a simple server designed to serve learning content built using PLCT. It may be launched locally using PLCT CLI or deployed as a standalone service. 

PLCT content is basically static HTML5, but some features of PLCT components may be limited without server-side support, like features based on AI or other server-side computation.

PLCT Server aims to provide the reference PLCT platform implementation suitable for development, demonstration, and simple production scenarios. PCLT Server is an OSS product designed to be easily adapted/integrated to meet specific needs.

## Install

*This doesn't work just now, but plct-serve will be publised on PYPI soon*

In youre active python environment just use the pip comand:

```
pip install plct-serve
```

Depending on how you have installed Python and configured active python environment, you may use alternative syntax to run the package installation.

## Running PLCT Server

You can run the PLCT Server either localy from command line (using an embeded web server) or deployed on a regular web server.

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


## Setting up development environment

You need to have installed Git, Pyton, Poetry and Node.js/npm. If you don't have experience with all those tools, take a look at how to use them.

Clone the repo into your local project folder.

Create a Python virtual environment for the project and make it active. You may use Poetry to create the virtual environment, but you also can keep using whatever you want since Poetry works well in any active Python virtual environment.

Take care to have the Python virtual environment acitvated before continue. If you use terminal/console integrated in your IDE, set it up to have an appropriate virutal environment activated.

Do initial install/build using npm:

```
pushd front-app
npm install
npm run build
popd
poetry install
```

It's also okay if you have done `poetry install` previousy.

## Run server in the development environment

You can run the PLCT Server using `plct-serve` command as it is explained in the Usage section above, since the `poetry install` command makes dev install of the package you are developing (like `pip -e .`).

When using the `plct-serve` command during development, you'll need to restart the server for any changes to take effect. Additionally, when you make changes to the React front-end, you need to execute `npm install`.

You can ran the dev-mode server on `http://localhost:8000` using the `dev-server.cmd` or `dev-server.sh` script (depending on your OS). When run this way, the server will do live-reload on any change in the `plct_server` package.

The *dev-server* script does't support arguments, but you may edit the `dev-server.json` file instaed. When you run the *dev-server* script first time, the `dev-server.json` file will be created as a copy of `dev-server.sample.json`. For more details on config options, refer to the [PLCT Server configuration](doc/config.md).

If you also require live reload for the React front-end, you can run the front-end server on `http://localhost:3000` by using the `npm start` command in the `front-app` folder.

Through the front-end URL, you have full access to the PLCT Server because the front-end server forwards all non-front-end requests to `http://localhost:8000`.

By using both the dev-mode server and the front-end server, you can achieve live reload for both the front-end and back-end changes.

## What is inside

The `plct_server` folder the Python package with a FastAPI based server and the `front-app` folder contains a React front-end. 

The `npm run build` command copies the `front-app\build` folder into `plct_server\front-app\build`. So, the FastAPI server servs both minimized bundles of the React front-end and the back-end API. FastAPI also serves some other web pages beyond th React front-end. 

Thus, the architecture combines a single-page application (SPA) and server-side rendering within a single server, while maintaining simplicity from the end-user's perspective.

## Batch Review Command

You can use the `batch-review` command to review conversation batches. This command helps in running batch reviews of conversations, setting benchmarks, and generating comparison reports.

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

**Example:**

```
plct batch-review -n test -v
```


This command will configure the server, run the batch prompts for conversations and generate an HTML report(`eval/result/test/`) comparing the responses.

The default conversations can be found in `eval/results/test/report.html`. You can group up sets of conversations into a single json file. Here is an example:

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
		"query": "Query",
		"response": "",
		"benchmark_response": "Benchmark response",
		"course_key": "course_key",
		"activity_key": "activity_key",
		"feedback": 0
	}
]
```