FROM python:3.12-slim

# This task starts from a working two-page site. The agent extends it, which
# means matching an existing design system rather than inventing one.
RUN mkdir -p /site /logs/verifier
COPY seed/ /site/

WORKDIR /site
