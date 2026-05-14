# syntax=docker/dockerfile:1
FROM python:3.12-slim

WORKDIR /app

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /usr/local/bin/

COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev

ENV PLAYWRIGHT_BROWSERS_PATH=/pw-browsers

# ARM64 (Apple Silicon Mac 등)에서는 Playwright 번들 chromium_headless_shell이
# QEMU 에뮬레이션으로 SEGFAULT 발생 → 시스템 Chromium 사용
RUN ARCH=$(dpkg --print-architecture) && \
    if [ "$ARCH" = "arm64" ]; then \
        apt-get update && \
        apt-get install -y --no-install-recommends chromium && \
        rm -rf /var/lib/apt/lists/* && \
        uv run playwright install-deps chromium ; \
    else \
        uv run playwright install-deps chromium && \
        uv run playwright install chromium ; \
    fi

COPY . .

CMD ["uv", "run", "python", "-m", "srt_watcher.main"]
