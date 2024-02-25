#!/bin/bash

if [ ! -f dev-server.json ]; then
    cp dev-server.sample.json dev-server.json
fi

export PLCT_SERVER_CONFIG_FILE=dev-server.json
uvicorn plct_server.main:app --reload --host "127.0.0.1" --port 8000
