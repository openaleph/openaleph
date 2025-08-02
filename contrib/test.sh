#!/bin/sh

psql -c "DROP DATABASE IF EXISTS aleph;" $ALEPH_DATABASE_URI
psql -c "CREATE DATABASE aleph;" $ALEPH_DATABASE_URI

opal-procrastinate init-db

pytest aleph/ --cov=aleph --cov-report html --cov-report lcov $@
