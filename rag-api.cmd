@ECHO OFF
IF NOT EXIST plct-server-config.yaml COPY plct-server-config-sample.yaml plct-server-config.yaml
set PLCT_SERVER_CONFIG_FILE=plct-server-config.yaml
uv run uvicorn plct_server.rag_main:app --reload --host 127.0.0.1 --port 9000