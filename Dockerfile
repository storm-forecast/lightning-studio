FROM python:3.11-slim
ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 OMP_NUM_THREADS=2 MKL_NUM_THREADS=2 CUDA_VISIBLE_DEVICES=""
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg chromium fonts-dejavu-core git ca-certificates libgomp1 libsndfile1 tini \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY requirements.txt requirements-lipsync.txt ./
RUN python -m pip install --index-url https://download.pytorch.org/whl/cpu torch==2.6.0 \
    && python -m pip install -r requirements.txt -r requirements-lipsync.txt
ENV CHROMIUM_BIN=/usr/bin/chromium LIPSYNC_PYTHON=/usr/local/bin/python \
    WAV2LIP_ROOT=/opt/wav2lip WAV2LIP_CHECKPOINT=/data/models/wav2lip-compatible.pth \
    VIDEO_OUTPUT_DIR=/data/output VIDEO_TIMEZONE=America/Belem VIDEO_PROFILE=lite VIDEO_AUTOSTART=false
COPY scripts ./scripts
COPY deploy ./deploy
RUN python scripts/bootstrap_runtime.py --code-only
COPY lightning_video_engine ./lightning_video_engine
COPY templates ./templates
COPY prompts ./prompts
ENTRYPOINT ["/usr/bin/tini", "--"]
CMD ["bash", "scripts/start.sh"]
