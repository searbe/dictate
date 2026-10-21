#!/usr/bin/env python3
"""Starts Dictate: python dictate.py (switches to .venv automatically). The app is in the dictate/ package."""
import dictate

if __name__ == "__main__":
    dictate.bootstrap()
    from dictate import app
    _lock = app.only_instance()
    app.App().run()
