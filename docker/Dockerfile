# Note: Force M1 to emulate amd64
FROM --platform=linux/amd64 python:3.10

# Install uv
# https://docs.astral.sh/uv/guides/integration/docker/#installing-uv
COPY --from=ghcr.io/astral-sh/uv:0.7 /uv /uvx /bin/

# Install apt dependencies
# caching: https://docs.docker.com/build/cache/optimize/#use-cache-mounts
RUN --mount=type=cache,target=/var/cache/apt,sharing=locked \
    --mount=type=cache,target=/var/lib/apt,sharing=locked \
    apt-get update --quiet=2 && \
    apt-get install -y --no-install-recommends apt-utils && \
    apt-get install -y \
        build-essential \
        curl \
        libjpeg-dev \
        libleptonica-dev \
        libtesseract-dev \
        libz-dev \
        poppler-utils \
        qpdf \
        tesseract-ocr \
        exiftool \
        && \
    apt-get install \
        --no-install-recommends \
        --assume-yes \
        --quiet=2 \
        `# Document extraction and OCR tools` \
        antiword \
        docx2txt \
        ghostscript \
        libwpd-tools \
        `# Audio extraction/manipulation tools` \
        ffmpeg \
        libmagic1 \
        `# Image & OCR tools` \
        imagemagick \
        `# Other dependencies` \
        libffi-dev \
        libxml2-dev \
        libxslt-dev

# set environment variables
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    # Disable tesseract multithreading for more scalable performance and
    # faster overall performance
    OMP_THREAD_LIMIT=1

WORKDIR /code

# Install Python dependencies
COPY pyproject.toml uv.lock .
# https://docs.astral.sh/uv/guides/integration/docker/#caching
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/venv \
    PATH="/venv/bin:$PATH"
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync

COPY . .

EXPOSE 5050

ARG options
ENV OPTIONS $options

CMD gunicorn $OPTIONS doctor.wsgi:application \
      --workers ${DOCTOR_WORKERS:-1} \
      --max-requests 1000 \
      --max-requests-jitter 100 \
      --timeout 5400 \
      --bind 0.0.0.0:5050
