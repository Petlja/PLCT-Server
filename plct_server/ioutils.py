"""This module contains simple I/O utilities for reading and writing 
   strings and JSON/YAML files. To keep it simple, it is tailored to
   needs of the specific procect and does not aim to become a general package.
   Similar packages may exist in other projects independetly."""

import json

import yaml

def read_str(path: str) -> str:
    with open(path, 'r', encoding='utf-8') as file:
        return file.read()
    
def write_str(path: str, content: str) -> None:
    with open(path, 'w', encoding='utf-8') as file:
        file.write(content)

def read_json(path: str) -> dict|list|int|str|float:
    with open(path, 'r', encoding='utf-8') as file:
        return json.load(file)
    
def write_json(path: str, content: dict|list|int|str|float) -> None:
    with open(path, 'w', encoding='utf-8') as file:
        json.dump(content, file, indent=2, ensure_ascii=False)

def read_yaml(path: str) -> dict|list|int|str|float:
    with open(path, 'r', encoding='utf-8') as file:
        return yaml.safe_load(file)
    
def write_yaml(path: str, content: dict|list|int|str|float) -> None:
    with open(path, 'w', encoding='utf-8') as file:
        yaml.dump(content, file, indent=2, default_flow_style=False, allow_unicode=True)
