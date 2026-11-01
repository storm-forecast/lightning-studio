"""Video Engine API: accepted data products, queued jobs and safe Lightning Agent adapters."""

from __future__ import annotations

import os
import threading
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from queue import Queue
from typing import Optional
from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel, Field

from .lightning_agent import ALLOWED_PRODUCTS
from .production import produce
from .job_store import JobStore
from .scheduling import interval_slot
from .wardrobe import wardrobe_for_job
from .youtube import QuotaExceeded, publish_bulletin


API = os.environ.get("LIGHTNING_API_URL", "https://lightning-agent.onrender.com").rstrip("/")
APP_URL = os.environ.get("LIGHTNING_APP_URL", f"{API}/app/")
VISUAL_MODE = os.environ.get("VIDEO_VISUAL_MODE", "app")
OUTPUT = Path(os.environ.get("VIDEO_OUTPUT_DIR", "/tmp/video-output"))
TOKEN = os.environ.get("VIDEO_ENGINE_TOKEN", "")
SCHEDULE_HOUR_UTC = os.environ.get("VIDEO_DAILY_HOUR_UTC", "")
AUTOSTART = os.environ.get("VIDEO_AUTOSTART", "false").strip().lower() in {"1", "true", "yes"}

class State(str, Enum):
    queued = "queued"
    rendering = "rendering"
    done = "done"
    failed = "failed"


class VideoRequest(BaseModel):
    produto: str = Field("deterministico_ecens", pattern="^(deterministico_ecens|probabilidade_ecens)$")
    titulo: str = Field(..., min_length=3, max_length=120)
    idioma: str = Field("pt-BR", pattern="^pt-BR$")


@dataclass
class Job:
    id: str
    request: VideoRequest
    state: State = State.queued
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    updated_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    error: Optional[str] = None
    output: Optional[str] = None
    wardrobe: Optional[dict] = None
    youtube: Optional[dict] = None


class Jobs:
    """Single-worker queue. Replace this adapter with Redis/RQ when scaling beyond one Render worker."""

    def __init__(self):
        self.items: dict[str, Job] = {}
        self.queue: Queue[str] = Queue()
        self.lock = threading.Lock()
        self.store = JobStore(OUTPUT / 'jobs.sqlite3')
        for payload in self.store.all():
            job = self._decode(payload)
            self.items[job.id] = job
            if job.state in (State.queued, State.rendering):
                job.state = State.queued
                self.persist(job)
                self.queue.put(job.id)
        threading.Thread(target=self._work, daemon=True, name="video-renderer").start()

    @staticmethod
    def _decode(payload):
        values = dict(payload)
        values['request'] = VideoRequest(**values['request'])
        values['state'] = State(values['state'])
        return Job(**values)

    def create(self, request: VideoRequest, schedule_key=None) -> Job:
        job = Job(id=uuid.uuid4().hex, request=request)
        payload = asdict(job)
        payload['request'] = request.model_dump()
        with self.lock:
            saved, inserted = self.store.add(payload, schedule_key)
            if not inserted:
                return self.items.get(saved['id']) or self._decode(saved)
            self.items[job.id] = job
        self.queue.put(job.id)
        return job

    def persist(self, job):
        payload = asdict(job)
        payload['request'] = job.request.model_dump()
        self.store.save(payload)

    def get(self, job_id: str) -> Optional[Job]:
        with self.lock:
            return self.items.get(job_id)

    def _work(self) -> None:
        while True:
            job = self.get(self.queue.get())
            if job is None:
                continue
            job.state, job.updated_at = State.rendering, datetime.now(timezone.utc).isoformat()
            self.persist(job)
            try:
                job.output = render(job)
                job.state = State.done
                job.youtube = publish(job)
            except Exception as exc:  # return a job error; never kill the worker thread
                job.state, job.error = State.failed, str(exc)
                import logging
                logging.exception("falha ao gerar vídeo %s", job.id)
            job.updated_at = datetime.now(timezone.utc).isoformat()
            self.persist(job)


class DailyScheduler:
    """Minimal daily scheduler; Render Cron or Redis can call the same `create` method at larger scale."""

    def __init__(self, queue: Jobs, hour_utc: str):
        self.queue, self.hour_utc, self.last_day = queue, hour_utc, None

    def start(self) -> None:
        if not self.hour_utc:
            return
        try:
            hour = int(self.hour_utc)
            if not 0 <= hour <= 23:
                raise ValueError
        except ValueError:
            raise RuntimeError("VIDEO_DAILY_HOUR_UTC deve estar entre 0 e 23")

        def loop() -> None:
            while True:
                now = datetime.now(timezone.utc)
                if now.hour == hour and self.last_day != now.date():
                    self.queue.create(VideoRequest(titulo=f"Boletim ECENS — {now:%d/%m/%Y}"))
                    self.last_day = now.date()
                threading.Event().wait(30)

        threading.Thread(target=loop, daemon=True, name="video-scheduler").start()


class IntervalScheduler:
    """Single-worker deployment; persistent job slots prevent repeat dispatches."""
    def __init__(self, queue, hours, timezone_name):
        self.queue, self.hours, self.timezone_name = queue, int(hours), timezone_name
        interval_slot(datetime.now(timezone.utc), self.hours, self.timezone_name)

    def tick(self, now):
        key, slot = interval_slot(now, self.hours, self.timezone_name)
        return self.queue.create(VideoRequest(titulo=f"Boletim ECENS — {slot:%d/%m/%Y %H:%M}"), schedule_key=key)

    def start(self):
        def loop():
            while True:
                try:
                    self.tick(datetime.now(timezone.utc))
                except Exception:
                    import logging
                    logging.exception('falha ao agendar boletim')
                threading.Event().wait(30)
        threading.Thread(target=loop, daemon=True, name='video-interval-scheduler').start()


def render(job: Job) -> str:
    """Run the saved editorial prompt with evidence and an audio-timed scene plan."""
    if VISUAL_MODE != "app":
        raise RuntimeError("o boletim dirigido exige VIDEO_VISUAL_MODE=app")
    OUTPUT.mkdir(parents=True, exist_ok=True)
    job.wardrobe = wardrobe_for_job(OUTPUT / job.id, datetime.fromisoformat(job.created_at))
    return str(produce(OUTPUT / job.id, api=API, app_url=APP_URL, title=job.request.titulo,
                       presentation_at=datetime.fromisoformat(job.created_at)))


def publish(job: Job) -> Optional[dict]:
    """Upload a finished bulletin; a YouTube failure is recorded without failing the video."""
    if not os.environ.get("YOUTUBE_REFRESH_TOKEN"):
        return None
    import logging
    try:
        return publish_bulletin(Path(job.output).parent, datetime.fromisoformat(job.created_at))
    except QuotaExceeded as exc:
        logging.warning("boletim %s não enviado ao YouTube: %s", job.id, exc)
        return {"error": str(exc), "quota": True}
    except Exception as exc:
        logging.exception("falha ao enviar boletim %s ao YouTube", job.id)
        return {"error": str(exc)}


jobs = Jobs()
# A Free web instance has 512 MB and is appropriate for the API only.  Rendering
# is dispatched by GitHub Actions by default; opt in only on a provisioned worker.
interval_hours = os.environ.get('VIDEO_INTERVAL_HOURS', '')
if AUTOSTART:
    if interval_hours:
        IntervalScheduler(jobs, interval_hours, os.environ.get('VIDEO_TIMEZONE','America/Belem')).start()
    else:
        DailyScheduler(jobs, SCHEDULE_HOUR_UTC).start()
app = FastAPI(title="Lightning Studio API", version="0.1.0")

from .city_shorts import AgentSource, Monitor
from .shorts_routes import router as shorts_router
app.include_router(shorts_router)

@app.on_event("startup")
def start_city_shorts():
    app.state.city_shorts = Monitor(AgentSource(API), os.environ.get('SHORTS_OUTPUT_DIR', str(OUTPUT / 'shorts')))
    if os.environ.get('SHORTS_MONITOR_ENABLED', '').lower() == 'true':
        app.state.city_shorts.start()

@app.on_event("shutdown")
def stop_city_shorts():
    if getattr(app.state, 'city_shorts', None):
        app.state.city_shorts.stop.set()



def guard(token: Optional[str]) -> None:
    if not TOKEN or token != TOKEN:
        raise HTTPException(401, "token de vídeo inválido")


@app.get("/health")
def health():
    return {"status": "ok", "products": sorted(ALLOWED_PRODUCTS), "queue_size": jobs.queue.qsize(),
            "visual_source": APP_URL, "visual_mode": VISUAL_MODE,
            "renderer_profile": os.environ.get("VIDEO_PROFILE", "full"), "autostart": AUTOSTART}


@app.post("/v1/videos", status_code=202)
def create_video(request: VideoRequest, x_video_token: Optional[str] = Header(None)):
    guard(x_video_token)
    return asdict(jobs.create(request))


@app.get("/v1/videos/{job_id}")
def get_video(job_id: str, x_video_token: Optional[str] = Header(None)):
    guard(x_video_token)
    job = jobs.get(job_id)
    if job is None:
        raise HTTPException(404, "job não encontrado")
    return asdict(job)
