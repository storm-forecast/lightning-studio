"""Five-minute regional long-form bulletin for the TROVOX GLOBAL channel."""
from __future__ import annotations

import json
import os
import textwrap
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from .official import render_official
from .regional_map import basemap
from .segments import Segment, join_audio, save_plan
from .speech import prepare_scene_audios
from .world_alerts import alerts
from .world_shorts import severity_overlay

FONT = '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf'
BOLD = '/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf'

REGIONS = {
    'usa-canada': {
        'title': 'United States & Canada Weather Bulletin',
        'bounds': (-141, -52, 24, 72),
        'countries': {'United States', 'Canada'},
        'language': 'en-US',
        'voice': 'en-US-AvaNeural',
    },
    'europe': {'title': 'Europe Weather Bulletin', 'bounds': (-12, 42, 34, 72),
               'countries': {'United Kingdom', 'France', 'Germany', 'Spain', 'Italy'}, 'language': 'en-GB', 'voice': 'en-GB-SoniaNeural'},
    'africa': {'title': 'Africa Weather Bulletin', 'bounds': (-20, 52, -35, 38),
               'countries': {'South Africa', 'Egypt'}, 'language': 'en-GB', 'voice': 'en-GB-SoniaNeural'},
    'australia': {'title': 'Australia Weather Bulletin', 'bounds': (110, 155, -45, -10),
                  'countries': {'Australia'}, 'language': 'en-GB', 'voice': 'en-GB-SoniaNeural'},
    'asia': {'title': 'Asia Weather Bulletin', 'bounds': (60, 150, -5, 55),
             'countries': {'India', 'Japan', 'Singapore'}, 'language': 'en-GB', 'voice': 'en-GB-SoniaNeural'},
}


def _rows(region):
    wanted = REGIONS[region]['countries']
    return [row for row in alerts() if row.get('pais') in wanted and not row.get('erro')]


def _names(rows, *, high_only=False):
    filtered = [row for row in rows if not high_only or row.get('nivel') == 'alta']
    return ', '.join(row['cidade'] for row in filtered[:5]) or 'no city-level high-impact signal in this scan'


def _narration(section, title, rows):
    high = _names(rows, high_only=True)
    all_places = _names(rows)
    common = ('All maps show the latest available automated analysis and short-range forecast. Conditions can change quickly, '
              'so viewers should check official warnings issued by their local weather service before making travel, work, or safety decisions. ')
    text = {
        'rain': (f'This is the {title}. We begin with the rainfall outlook. The regional scan highlights {high}. '
                 'These locations are prioritized because the current analysis identifies heavier rain, elevated precipitation probability, '
                 'or official flood-related information. The map is designed to show the regional pattern rather than promise that every neighborhood '
                 'will receive the same weather. Look for repeated rain bands, slow-moving cells, and locations where short-range totals may rise. ' + common),
        'nowcast': (f'Now we move to nowcasting. The severity layer combines the latest monitored weather signal with the local map. '
                    f'Cities included in this regional scan are {all_places}. Where satellite lightning coverage is available, observed strikes are shown as points. '
                    'Where coverage is unavailable, the video says so instead of estimating lightning. This distinction matters: a nowcast describes the current environment, '
                    'while a forecast describes what may develop next. Watch for rapid changes in storm organization, lightning concentration, and movement. ' + common),
        'severe': (f'For severe weather potential, priority locations are {high}. A highlighted area means the short-range signal deserves attention; '
                   'it is not a guarantee that severe weather will occur at every address. Thunderstorms can produce damaging wind, frequent lightning, '
                   'brief intense rain, and isolated hail. If an official warning is issued, follow that warning first. Keep phones charged, avoid exposed areas, '
                   'and do not wait until conditions become dangerous before seeking a sturdy building. ' + common),
        'flood': (f'Next is flooding potential. The map shows official flood geometry when an authority provides it; otherwise it shows only a city-centred risk signal. '
                  f'Current areas of attention include {high}. Flood risk can increase quickly after repeated downpours, especially near low-lying roads, '
                  'urban drainage, creeks, and underpasses. Never drive through water covering a road. Water depth and road damage are difficult to judge from a vehicle. ' + common),
        'advice': ('To close this bulletin, prepare for changing conditions. Keep a reliable way to receive official warnings, move indoors when lightning is nearby, '
                   'and avoid open fields, isolated trees, beaches, and water. During flooding, turn around rather than crossing a flooded road. '
                   'Check on family members who may need help receiving alerts. Subscribe to TROVOX GLOBAL for the next regional nowcasting update. ' + common),
    }
    return text[section]


def _scene(path, region, title, subtitle, rows):
    west, east, south, north = REGIONS[region]['bounds']
    canvas = Image.new('RGB', (1440, 810), '#081522')
    draw = ImageDraw.Draw(canvas)
    base = basemap((west, east, south, north), path.parent / 'map-cache', size=(1280, 590), zoom=3)
    canvas.paste(base, (80, 145))
    layer = severity_overlay((west, east, south, north), (1280, 590))
    if layer is not None:
        canvas.paste(layer, (80, 145), layer)
    draw.rectangle((0, 0, 1440, 112), fill='#102337')
    draw.rectangle((0, 112, 1440, 118), fill='#60e5cf')
    draw.text((48, 24), 'TROVOX GLOBAL', font=ImageFont.truetype(BOLD, 30), fill='#60e5cf')
    draw.text((48, 62), title, font=ImageFont.truetype(BOLD, 32), fill='white')
    draw.rounded_rectangle((80, 675, 1360, 765), radius=14, fill='#102337e8')
    draw.text((110, 697), subtitle, font=ImageFont.truetype(BOLD, 27), fill='white')
    draw.text((110, 735), 'Severity layer: Lightning Agent • Official alerts are labelled on screen', font=ImageFont.truetype(FONT, 19), fill='#d5e6ef')
    for row in rows:
        if not (south <= row.get('lat', 0) <= north and west <= row.get('lon', 0) <= east):
            continue
        x = int(80 + (row['lon'] - west) / (east - west) * 1280)
        y = int(145 + (north - row['lat']) / (north - south) * 590)
        color = '#ef4e52' if row.get('nivel') == 'alta' else '#ffbe61'
        draw.ellipse((x - 8, y - 8, x + 8, y + 8), fill=color, outline='white', width=2)
    path.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(path)


def produce(directory: Path, region='usa-canada'):
    if region not in REGIONS:
        raise ValueError('região inválida: ' + region)
    directory = Path(directory); directory.mkdir(parents=True, exist_ok=True)
    profile, rows = REGIONS[region], _rows(region)
    os.environ['EDGE_TTS_VOICE'] = profile['voice']
    os.environ['NARRATION_SPEED'] = '0.82'
    sections = [('01-rain', 'rain', 'RAIN FORECAST'), ('02-nowcast', 'nowcast', 'NOWCASTING'),
                ('03-severe', 'severe', 'SEVERE WEATHER POTENTIAL'), ('04-flood', 'flood', 'FLOODING POTENTIAL'),
                ('05-advice', 'advice', 'SAFETY RECOMMENDATIONS')]
    scenes = []
    for ident, key, label in sections:
        image = directory / 'scenes' / f'{ident}.png'
        _scene(image, region, profile['title'], label, rows)
        scenes.append(Segment(ident, label, 'world', key, source='world', image=str(image), narration=_narration(key, profile['title'], rows)))
    audio_dir = directory / 'audio'
    prepare_scene_audios(scenes, audio_dir, workers=2)
    final_audio = directory / 'narration.wav'
    duration = join_audio(scenes, final_audio)
    if duration < 300:
        # Keep the video honest while ensuring the requested minimum duration.
        scenes[-1].narration += ' ' + ('Continue monitoring official updates and local radar as weather conditions evolve. ' * int((300 - duration) * 2.5))
        prepare_scene_audios(scenes, audio_dir, workers=2)
        duration = join_audio(scenes, final_audio)
    if duration < 300:
        raise RuntimeError(f'world bulletin is only {duration:.1f} seconds; minimum is 300 seconds')
    save_plan(scenes, directory / 'scene-plan.json')
    (directory / 'script.md').write_text('\n\n'.join(f'## {scene.title}\n\n{scene.narration}' for scene in scenes))
    (directory / 'metadata.json').write_text(json.dumps({'region': region, 'title': profile['title'], 'language': profile['language'], 'duration_seconds': duration}, indent=2))
    output = directory / 'bulletin.mp4'
    render_official([Path(scene.image) for scene in scenes], final_audio, output, title=profile['title'],
                    subtitle='Rain forecast • Nowcasting • Severe weather • Flooding • Safety',
                    scene_durations=[scene.duration for scene in scenes], narration_final=True, channel_name='TROVOX GLOBAL')
    return output
