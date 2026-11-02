#!/usr/bin/env python3
"""Upload a completed long-form bulletin only to the dedicated TROVOX GLOBAL channel."""
import json
import os
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from lightning_video_engine.app.youtube import access_token, authorized_channel, upload, YouTubeError

directory = Path(sys.argv[1])
video = directory / 'bulletin.mp4'
meta = json.loads((directory / 'metadata.json').read_text())
required = ('WORLD_YOUTUBE_CLIENT_ID', 'WORLD_YOUTUBE_CLIENT_SECRET', 'WORLD_YOUTUBE_REFRESH_TOKEN', 'WORLD_YOUTUBE_CHANNEL_ID')
missing = [name for name in required if not os.environ.get(name)]
if missing: raise SystemExit('missing ' + ', '.join(missing))
token = access_token(os.environ['WORLD_YOUTUBE_CLIENT_ID'], os.environ['WORLD_YOUTUBE_CLIENT_SECRET'], os.environ['WORLD_YOUTUBE_REFRESH_TOKEN'])
channel, name = authorized_channel(token)
if channel != os.environ['WORLD_YOUTUBE_CHANNEL_ID']:
    raise SystemExit(f'world token belongs to {channel} ({name}), not the configured TROVOX GLOBAL channel')
metadata = {'snippet': {'title': meta['title'][:100], 'description': (
    'TROVOX GLOBAL long-form weather bulletin.\n\n'
    'Rain forecast, nowcasting, severe-weather potential, flooding information, and safety recommendations. '
    'Check official weather services for warnings in your area.\n\n#weather #nowcasting #severeweather'),
    'categoryId': '25', 'defaultLanguage': meta['language'], 'defaultAudioLanguage': meta['language'],
    'tags': ['weather', 'nowcasting', 'severe weather', 'flooding', 'TROVOX GLOBAL']},
    'status': {'privacyStatus': 'public', 'selfDeclaredMadeForKids': False, 'containsSyntheticMedia': True}}
result = upload(video, metadata, token)
if not result.get('id'): raise YouTubeError('YouTube did not return a video ID')
record = {'video_id': result['id'], 'url': f"https://youtu.be/{result['id']}", 'channel_id': channel, 'title': meta['title'], 'duration_seconds': meta['duration_seconds']}
(directory / 'youtube.json').write_text(json.dumps(record, indent=2))
print(record['url'])
