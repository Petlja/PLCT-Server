# PLCT Server

*This project is in the proof-of-concept stage.*

PLCT (Petlja Learning Content Tools) Server is a simple server designed to serve learning content built using PLCT. It may be launched locally using PLCT CLI or deployed as a standalone service. 

PLCT content is basically static HTML5, but some features of PLCT components may be limited without server-side support, like features based on AI or other server-side computation.

PLCT Server aims to provide the reference PLCT platform implementation suitable for development, demonstration, and simple production scenarios. PCLT Server is an OSS product designed to be easily adapted/integrated to meet specific needs.

## Usage

You can run the PLCT Server either localy from command line (using an embeded web server) or deployed on a regular web server.

Ways to run localy from command line:
- use the `plct-serve` shell command:  
  ```
  plct-serve [OPTIONS] [FOLDERS]
  ```
- use as an extension of a Python CLI app that is based on the `click` package, like with PLCT CLI:  
  ```
  plct serve [OPTIONS] [FOLDERS]
  ```

PLCT Server can be [deployed as a FastAPI app](https://fastapi.tiangolo.com/deployment/), or more generally, as a Python ASGI web application that is supported by most web servers and PaaS providers:
- run the `plct_server.main:app` using an ASGI web server and the `PLCT_SERVER_CONFIG_FILE` environment variable

- embed the PLCT Server into your FastAPI app using the `router` object from the `plct_server.endpoints` module

When deploying a PLCT website, the content is included in the deployment, similar to a static website, but with additional server-side processing. More dynamic content management and configuration may be implemented in an embedding FastAPI app.

> TODO: explain each way in more detailes