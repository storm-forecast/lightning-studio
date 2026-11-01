#!/usr/bin/env python3
"""Run the same Studio city monitor as a dedicated local worker."""
import os
import sys
import signal
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from lightning_video_engine.app.city_shorts import AgentSource, Monitor
root=Path(os.environ.get('SHORTS_OUTPUT_DIR',str(Path(__file__).resolve().parents[1]/'output/shorts')))
monitor=Monitor(AgentSource(os.environ.get('LIGHTNING_API_URL','https://lightning-agent.onrender.com')),root)
signal.signal(signal.SIGTERM,lambda *_:monitor.stop.set())
signal.signal(signal.SIGINT,lambda *_:monitor.stop.set())
monitor.start()
monitor.stop.wait()
