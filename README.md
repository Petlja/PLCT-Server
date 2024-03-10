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

## Usage

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

Use `plct-serve --help` to se supported options.

PLCT Server can be [deployed as a FastAPI app](https://fastapi.tiangolo.com/deployment/), or more generally, as a Python ASGI web application that is supported by most web servers and PaaS providers:
- run the `plct_server.main:app` using an ASGI web server and the `PLCT_SERVER_CONFIG_FILE` environment variable

- embed the PLCT Server into your FastAPI app (source of the `plct_server.main` module may be a starting point)

When deploying a PLCT website, the content is included in the deployment, similar to a static website, but with additional server-side processing. More dynamic content management and configuration may be implemented in an embedding FastAPI app.

> TODO: explain each way in more detailes

## Setting up development environment

You need to have installed Git, Pyton, Poetry and Node.js/npm. If you don't have experience with all those tools, take a look at how to use them.

Clone the repo into your local project folder.

Create a Python virtual environment for the project and make it active. You may use Poetry to create the virtual environment, but you also can keep using whatever you want since Poetry works well in any active Python virtual environment.

Take care to have the Python virtual environment acitvated before continue. If you use terminal/console integrated in your IDE, set it up to have an appropriate virutal environment activated.

Do initial install/build using npm:

```
pushd front-app
npm install
npm build
popd
poetry install
```

It's also okay if you have done `poetry install` previousy.

## What is inside

The `plct_server` folder the Python package with a FastAPI based server and the `front-app` folder contains a React front-end. 

The `npm run build` command copies the `front-app\build` folder into `plct_server\front-app\build`. So, the FastAPI server servs both minimized bundles of the React front-end and the back-end API. FastAPI also serves some other web pages beyond th React front-end. 

Thus, the architecture combines a single-page application (SPA) and server-side rendering within a single server, while maintaining simplicity from the end-user's perspective.

## Run server in the development environment

You can run the PLCT Server using `plct-serve` command as it is explained in the Usage section above, since the `poetry install` command makes dev install of the package you are developing (like `pip -e .`).

When using the `plct-serve` command during development, you'll need to restart the server for any changes to take effect. Additionally, when you make changes to the React front-end, you need to execute `npm install`.

You can ran the dev-mode server on `http://localhost:8000` using the `dev-server.cmd` or `dev-server.sh` script (depending on your OS). When run this way, the server will do live-reload on any change in the `plct_server` package.

The *dev-server* script does't support arguments, but you may edit the `dev-server.json` file instaed. When you run the *dev-server* script first time, the `dev-server.json` file will be created as a copy of `dev-server.sample.json`.

If you also require live reload for the React front-end, you can run the front-end server on `http://localhost:3000` by using the `npm start` command in the `front-app` folder.

Through the front-end URL, you have full access to the PLCT Server because the front-end server forwards all non-front-end requests to `http://localhost:8000`.

By using both the dev-mode server and the front-end server, you can achieve live reload for both the front-end and back-end changes.

# Using AI context dataset

Yo can use `--ai-context` CLI or `ai_context_dir` config file option to specify the directory of a context dataset.

Yo can use `plct_server.ai.context_dataset` module in you scipt to create context dataset. 

