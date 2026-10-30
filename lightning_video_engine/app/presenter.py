"""Presenter-video contract.

Lip sync is deliberately separate from weather analysis.  A configured provider
must return an MP4/WebM with alpha or a keyable background; this module never
pretends a still image has moving speech.
"""
from __future__ import annotations

import os
from pathlib import Path


def presenter_video() -> Path | None:
    """Return the reusable visual clip; its source audio is never used."""
    value = os.environ.get("PRESENTER_VIDEO", "")
    if value:
        path = Path(value)
        if not path.is_file():
            raise RuntimeError("PRESENTER_VIDEO aponta para um arquivo inexistente")
        return path
    bundled = Path(__file__).resolve().parents[2] / "templates" / "apresentadora-base.mp4"
    return bundled if bundled.is_file() else None



def require_presenter_video() -> Path:
    clip = presenter_video()
    if not clip:
        raise RuntimeError("avatar animado não configurado: defina PRESENTER_VIDEO com MP4/WebM sincronizado")
    return clip
