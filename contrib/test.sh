#!/bin/sh

pip install -r requirements-dev.txt
pytest -s aleph/tests $@
