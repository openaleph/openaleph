#!/bin/sh

psql -c "DROP DATABASE IF EXISTS aleph;" $ALEPH_DATABASE_URI
psql -c "CREATE DATABASE aleph;" $ALEPH_DATABASE_URI

# FIXME
pip3 install procrastinate==3.2.2

pytest aleph/ --cov=aleph --cov-report html --cov-report lcov $@
