#!/usr/bin/env python3
"""Watch city and global conditions continuously and publish Shorts as soon as a trigger holds.

Each pass runs in a child process with a hard time limit, so a stalled source or encoder
ends that pass instead of the watcher; the persisted state lets the next pass resume.
"""
import argparse
import json
import os
import signal
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def log(*values):
    print(f'[{datetime.now(timezone.utc):%H:%M:%SZ}]', *values, flush=True)


def one_pass():
    from lightning_video_engine.app.city_shorts import AgentSource
    from lightning_video_engine.app.shorts_runs import (DeferredMonitor, app_url, capture_flood_areas,
                                                        publish_cities, publish_world, scan_cities)

    failed = False
    city_root = Path(os.environ.get('SHORTS_OUTPUT_DIR', 'output/shorts'))
    city_root.mkdir(parents=True, exist_ok=True)
    try:
        source = AgentSource(os.environ.get('LIGHTNING_API_URL', 'https://lightning-agent.onrender.com'))
        monitor = DeferredMonitor(source, city_root)
        areas = capture_flood_areas(city_root, app_url())
        scan = scan_cities(monitor, source, areas)
        (city_root / 'scan.json').write_text(json.dumps(scan, ensure_ascii=False, indent=2))
        log('Cidades com alerta:', ', '.join(scan['candidatas']) or 'nenhuma',
            f"| falhas de consulta: {len(scan['erros'])}")
        lines, city_failed = publish_cities(monitor, city_root, scan['relatorios'])
        failed |= city_failed
        for line in lines:
            log('Cidades:', line)
    except Exception as exc:
        failed = True
        log('Cidades: falha no ciclo:', exc)
    try:
        for line in publish_world(Path(os.environ.get('WORLD_SHORTS_OUTPUT_DIR', 'output/world-shorts'))):
            log('Global:', line)
    except Exception as exc:
        failed = True
        log('Global: falha no ciclo:', exc)
    return failed


def watch(minutes, interval, pass_limit):
    """Repeat passes until the time budget no longer fits a full pass."""
    deadline = time.monotonic() + minutes * 60
    passes = failures = 0
    while time.monotonic() + pass_limit < deadline:
        started = time.monotonic()
        passes += 1
        # A session of its own lets a timeout also stop the encoders the pass started.
        child = subprocess.Popen([sys.executable, __file__, '--once'], cwd=ROOT, start_new_session=True)
        try:
            code = child.wait(timeout=pass_limit)
        except subprocess.TimeoutExpired:
            os.killpg(child.pid, signal.SIGKILL)
            child.wait()
            code = 'timeout'
            log(f'Ciclo {passes} excedeu {pass_limit}s e foi encerrado; seguindo para o próximo.')
        failures += code != 0
        time.sleep(max(30, interval - (time.monotonic() - started)))
    log(f'Janela encerrada: {passes} ciclos, {failures} com falha.')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--once', action='store_true', help='run a single pass')
    parser.add_argument('--minutes', type=float, default=float(os.environ.get('WATCH_MINUTES', 320)))
    parser.add_argument('--interval', type=int, default=int(os.environ.get('WATCH_INTERVAL_SECONDS', 300)))
    parser.add_argument('--pass-limit', type=int, default=int(os.environ.get('WATCH_PASS_LIMIT_SECONDS', 1500)))
    args = parser.parse_args()
    if args.once:
        raise SystemExit(1 if one_pass() else 0)
    watch(args.minutes, args.interval, args.pass_limit)
