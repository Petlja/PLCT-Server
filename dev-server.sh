#!/bin/bash

if [ ! -f plct-server-config.yaml ]; then
    cp plct-server-config-sample.yaml plct-server-config.yaml
fi

export PLCT_SERVER_CONFIG_FILE=plct-server-config.yaml
uvicorn plct_server.ui_main:app --reload --host "127.0.0.1" --port 9000
