#!/usr/bin/env python3
"""Produce the daily South America bulletin from the day's forecast files."""
import argparse
from datetime import datetime
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from lightning_video_engine.app.south_america_bulletin import produce

p = argparse.ArgumentParser(description=__doc__)
p.add_argument('--directory', type=Path, required=True)
p.add_argument('--publish-at', help='ISO-8601 instant of publication; it decides what "today" means')
a = p.parse_args()
print(produce(a.directory, publish_at=datetime.fromisoformat(a.publish_at.replace('Z', '+00:00')) if a.publish_at else None))
