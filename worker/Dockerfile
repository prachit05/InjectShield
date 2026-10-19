# Build from the repo root: docker build -f worker/Dockerfile .
# Add --build-arg INSTALL_CLASSIFIER=true to include the optional classifier (much larger image).
FROM python:3.11-slim

ARG INSTALL_CLASSIFIER=false
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /srv

COPY shared /srv/shared
COPY worker/requirements.txt worker/requirements-classifier.txt /srv/worker/
RUN pip install /srv/shared -r /srv/worker/requirements.txt \
 && if [ "$INSTALL_CLASSIFIER" = "true" ]; then pip install -r /srv/worker/requirements-classifier.txt; fi

COPY worker/injectshield_worker /srv/injectshield_worker

RUN useradd --uid 10001 --create-home --shell /usr/sbin/nologin app
USER app

CMD ["python", "-m", "injectshield_worker.main"]
