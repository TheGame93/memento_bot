import os
import sys


def find_project_root(start_path: str) -> str:
    current = os.path.abspath(os.path.dirname(start_path))
    while True:
        if os.path.exists(os.path.join(current, "mainbot.py")) and os.path.isdir(os.path.join(current, "modules")):
            return current
        parent = os.path.dirname(current)
        if parent == current:
            return os.path.abspath(os.path.join(os.path.dirname(start_path), "..", "..", ".."))
        current = parent


def ensure_on_path(path: str):
    if path not in sys.path:
        sys.path.insert(0, path)


def add_project_root_to_path(start_path: str) -> str:
    root = find_project_root(start_path)
    ensure_on_path(root)
    return root
