#!/usr/bin/env python3
"""Publish at most one high-condition global rain Short per city per UTC day."""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from lightning_video_engine.app.shorts_runs import publish_world

for line in publish_world(Path(os.environ.get('WORLD_SHORTS_OUTPUT_DIR', 'output/world-shorts')),
                          os.environ.get('WORLD_CITY', '').strip()):
    print(line, flush=True)
