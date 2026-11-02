#!/usr/bin/env python3
import argparse
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from lightning_video_engine.app.world_bulletin import REGIONS, produce
p = argparse.ArgumentParser()
p.add_argument('--directory', type=Path, required=True)
p.add_argument('--region', choices=sorted(REGIONS), default='usa-canada')
a = p.parse_args()
print(produce(a.directory, a.region))
