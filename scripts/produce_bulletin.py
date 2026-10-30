#!/usr/bin/env python3
"""Produce a scene-directed bulletin from the saved prompt and official template."""
import argparse
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from lightning_video_engine.app.production import produce
p=argparse.ArgumentParser(description=__doc__)
p.add_argument('--directory',type=Path,required=True)
p.add_argument('--api',default='https://lightning-agent.onrender.com')
p.add_argument('--capture-only',action='store_true')
a=p.parse_args()
produce(a.directory,api=a.api,capture_only=a.capture_only)
