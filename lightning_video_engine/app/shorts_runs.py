"""One monitoring pass for city and global Shorts, shared by the CLI checks and the watcher."""
import json
import os
from concurrent.futures import ThreadPoolExecutor, TimeoutError as PassTimeout, as_completed
from datetime import datetime, timezone
from pathlib import Path

from .city_shorts import CITIES, Monitor, utc_now
from .sp_flood_shorts import SP_FLOOD_CITIES
from .youtube import QuotaExceeded, block_quota, publish_short, quota_blocked_until

# An alert older than this is not rendered: the next pass re-reads it with fresh data,
# leaving the render enough time inside the 15-minute publication limit.
MAX_RENDER_AGE = 540


class DeferredMonitor(Monitor):
    """Collect dispatched jobs instead of starting daemon threads; the caller renders them."""

    def work(self, item, **_):
        self.pending.append(item)


def scan_cities(monitor, source, flood_areas=(), *, workers=6, deadline=240):
    """Evaluate every eligible city in parallel; a slow city is reported, never awaited past the deadline."""
    from .sp_flood_zones import confirmed_zones

    def evaluate(key):
        if not monitor.eligible(key):
            return None
        report = monitor.evaluate_city(key)
        if key in SP_FLOOD_CITIES and flood_areas:
            name, state, _, _ = CITIES[key]
            zones = confirmed_zones(source, name, state, flood_areas)
            if zones:
                report['flood_zones'] = zones
                report['zona_id'] = zones[0]['zona_id']
                report['gerar'] = True
                report['motivos'] = ['polígono oficial de potencial de alagamento associado ao município']
        return report

    reports, errors = {}, []
    pool = ThreadPoolExecutor(workers, thread_name_prefix='city-scan')
    futures = {pool.submit(evaluate, key): key for key in CITIES}
    try:
        for future in as_completed(futures, timeout=deadline):
            try:
                report = future.result()
            except Exception as exc:
                errors.append({'cidade': futures[future], 'erro': str(exc)})
                continue
            if report and report['gerar']:
                reports[futures[future]] = report
    except PassTimeout:
        errors.extend({'cidade': key, 'erro': 'sem resposta no prazo da varredura'}
                      for future, key in futures.items() if not future.done())
    finally:
        pool.shutdown(wait=False, cancel_futures=True)
    order = list(CITIES)
    candidates = sorted(reports, key=order.index)
    return {'candidatas': candidates, 'relatorios': {key: reports[key] for key in candidates}, 'erros': errors}


def report_age(report):
    checked = datetime.fromisoformat(report['verificado_em'].replace('Z', '+00:00')).replace(tzinfo=None)
    return (utc_now() - checked).total_seconds()


def publish_cities(monitor, root, reports):
    """Render and publish reserved candidates one by one; returns (lines, failed)."""
    monitor.pending = []
    result = monitor.check(reports=reports)
    lines, failed = [], False
    for report in result['resultados']:
        if report.get('erro'):
            failed = True
            lines.append(f"{report['cidade']}: {report['erro']}")
        ident = report.get('video_id')
        if not ident:
            continue
        item = monitor.get(ident)
        if quota_blocked_until(root):
            # Do not render videos that can no longer be uploaded today.
            item.update(estado='falhou', erro='quota do YouTube esgotada; não renderizado')
            monitor.save(item)
            continue
        if report_age(item['alerta']) > MAX_RENDER_AGE:
            item.update(estado='falhou', erro='alerta envelhecido na fila; nova verificação no próximo ciclo')
            monitor.save(item)
            lines.append(f"{report['cidade']}: adiado para nova verificação")
            continue
        Monitor.work(monitor, item)
        item = monitor.get(ident)
        youtube = item.get('youtube', {})
        lines.append(f"{report['cidade']} {item['estado']} {json.dumps(youtube, ensure_ascii=False)}")
        if item['estado'] == 'falhou' and not youtube.get('quota'):
            failed = True
    return lines, failed


def publish_world(root, requested=''):
    """Publish high-condition global Shorts, at most one per city per UTC day; returns printed lines."""
    from .world_shorts import candidates, render, report
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    until = quota_blocked_until(root)
    if until:
        return [f'Quota do YouTube esgotada até {until.isoformat()} — monitor parado.']
    history_file = root / 'published.json'
    history = json.loads(history_file.read_text()) if history_file.exists() else {}
    today = datetime.now(timezone.utc).date().isoformat()
    rows = [row for row in candidates() if history.get(row['id']) != today]
    if requested:
        wanted = {value.strip() for value in requested.lower().split(',') if value.strip()}
        rows = [row for row in rows if row['id'] in wanted]
    if not rows:
        return ['Nenhuma condição global alta nova.']
    lines = []
    for row in rows[:2 if requested else 1]:
        item = report(row)
        directory = root / f"{item['cidade']}-{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}"
        render(directory, item)
        try:
            saved = publish_short(directory, prefix='WORLD_YOUTUBE', brand='TROVOX GLOBAL')
        except QuotaExceeded as exc:
            until = block_quota(root, str(exc))
            lines.append(f'Quota do YouTube esgotada até {until.isoformat()} — monitor parado.')
            break
        history[item['cidade']] = today
        history_file.write_text(json.dumps(history, ensure_ascii=False, indent=2))
        lines.append(f"Published: {saved['url']}")
    return lines


def capture_flood_areas(root, app_url):
    """Refresh the official flood polygons; keep the previous capture when the app is unavailable."""
    from .directed_scenes import capture_flood_areas as capture
    path = Path(root) / 'flood-areas.json'
    try:
        path.write_text(json.dumps(capture(app_url), ensure_ascii=False))
    except Exception as exc:
        print('Polígonos de alagamento indisponíveis:', exc, flush=True)
    return json.loads(path.read_text()) if path.exists() else []


def app_url():
    api = os.environ.get('LIGHTNING_API_URL', 'https://lightning-agent.onrender.com').rstrip('/')
    return os.environ.get('LIGHTNING_APP_URL', api + '/app/')
