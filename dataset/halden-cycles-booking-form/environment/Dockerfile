# Chromium only, and only the libraries headless Chromium actually needs.
#
# `playwright install --with-deps chromium` pulls 325MB of apt — xvfb, CJK
# fonts, mesa-dri, llvm — none of which headless Chromium uses. Verified
# locally: this image launches Chromium and passes the verifier, at 1.64GB
# instead of 2.02GB.
#
# Pinned to bookworm because Playwright 1.49.1's apt list names ttf-unifont
# and ttf-ubuntu-font-family, both renamed in Debian trixie.
FROM python:3.12-slim-bookworm

RUN apt-get update && apt-get install -y --no-install-recommends \
      libnss3 libnspr4 libatk1.0-0 libatk-bridge2.0-0 libatspi2.0-0 \
      libcups2 libdrm2 libgbm1 libxkbcommon0 libxcomposite1 libxdamage1 \
      libxfixes3 libxrandr2 libx11-6 libxcb1 libxext6 \
      libpango-1.0-0 libcairo2 libasound2 fonts-liberation \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir playwright==1.49.1 \
    && playwright install chromium

# The site the agent edits. A copy of ../../scaffold — Docker can only COPY
# from inside the build context, which Harbor sets to this environment/ dir.
#
# mkdir is folded into this COPY's layer rather than its own RUN: in the
# LangSmith builder each layer commit costs about ten seconds regardless of
# content, and a `RUN mkdir` plus a bare `WORKDIR` were costing 21s between
# them to create one empty directory.
COPY site/ /app/site/
RUN mkdir -p /logs/verifier
WORKDIR /app/site
