FROM python:3.12-slim

# Harbor stages the agent's own virtualenv into the container at run time, so
# this image needs almost nothing: a working python3 for the stdlib-only
# verifier, and an empty site root for the agent to build into.
RUN mkdir -p /site /logs/verifier

WORKDIR /site
