FROM python:3.12-slim

# This task starts from an existing, broken site rather than an empty folder:
# the agent has to read what is there, find the damage, and repair it without
# rewriting the copy.
RUN mkdir -p /site /logs/verifier
COPY seed/ /site/

WORKDIR /site
