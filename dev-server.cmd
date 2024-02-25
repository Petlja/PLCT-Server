@ECHO OFF
IF NOT EXIST dev-server.json COPY dev-server.sample.json dev-server.json
set PLCT_SERVER_CONFIG_FILE=dev-server.json
uvicorn plct_server.main:app --reload --host 127.0.0.1 --port 8000
