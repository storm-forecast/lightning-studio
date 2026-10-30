#!/usr/bin/env python3
"""Render a reusable bulletin from existing official map images and narration."""
import argparse
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from lightning_video_engine.app.broadcast import compose
from lightning_video_engine.app.official import render_official

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--maps', type=Path, nargs='+', required=True)
parser.add_argument('--audio', type=Path, required=True)
parser.add_argument('--presenter', type=Path)
parser.add_argument('--output', type=Path, required=True)
parser.add_argument('--title', default='Boletim meteorológico')
parser.add_argument('--subtitle', required=True, help='Período válido dos dados ou identificação de prévia')
parser.add_argument('--timing-final', action='store_true',
                    help='Áudio e apresentadora já sincronizados; não alterar velocidades')
parser.add_argument('--official', action='store_true', help='Template oficial com sincronização labial por roteiro')
args = parser.parse_args()
if args.official:
    if args.presenter or args.timing_final:
        parser.error('--official usa PRESENTER_VIDEO e calcula o sincronismo automaticamente')
    render_official(args.maps, args.audio, args.output, title=args.title, subtitle=args.subtitle)
else:
    compose(args.maps, args.audio, args.output, title=args.title,
            subtitle=args.subtitle, presenter=args.presenter, timing_final=args.timing_final)
print(args.output)
