import uvicorn
from plct_server.main import app

def run() -> None:
    uvicorn.run(app, host="127.0.0.1", port=8000)