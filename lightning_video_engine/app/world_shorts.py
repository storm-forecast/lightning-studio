"""Independent global rain Shorts for the TROVOX GLOB YouTube channel."""
import asyncio
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from .world_alerts import alerts

FONT = '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf'
BOLD = '/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf'


def candidates():
    """Only high rain conditions produce automatic global videos."""
    return [row for row in alerts() if row.get('nivel') == 'alta' and not row.get('erro')]


def report(row):
    now = datetime.now(timezone.utc)
    city, country = row['cidade'], row['pais']
    current = row['chuva_atual_mm']
    probability = row['probabilidade_6h']
    observed = (f"Rain is currently observed at {current:.1f} millimetres." if current > 0
                else "No rain is measured at this point right now.")
    script = (f"Global rain update for {city}, {country}. {observed} "
              f"The highest precipitation probability over the next six hours is {probability} percent. "
              "This is an automated weather estimate, not an official warning. "
              "Follow your local weather service and emergency guidance.")
    return {'cidade': row['id'], 'nome': city, 'uf': country, 'pais': country,
            'verificado_em': now.isoformat().replace('+00:00', 'Z'), 'gerar': True,
            'motivos': ['condição alta de chuva ou probabilidade elevada nas próximas seis horas'],
            'roteiro': script, 'recomendacoes': ['Acompanhe o serviço meteorológico local.',
                                                  'Siga as orientações oficiais de emergência.'],
            'timezone': row.get('timezone', 'UTC'), 'idioma': 'en-US', 'fonte': 'Open-Meteo', 'oficial': False,
            'chuva_atual_mm': current, 'probabilidade_6h': probability,
            'titulo_short': f"{city}: chuva e previsão nas próximas horas #Shorts"}


def render(directory: Path, item):
    """Render a compact narrated card; global data is never presented as an official warning."""
    import edge_tts
    directory.mkdir(parents=True, exist_ok=True)
    (directory / 'alerta.json').write_text(json.dumps(item, ensure_ascii=False, indent=2))
    asyncio.run(edge_tts.Communicate(item['roteiro'], 'en-US-AvaNeural').save(str(directory / 'voz.mp3')))
    image = Image.new('RGB', (720, 1280), '#081522')
    draw = ImageDraw.Draw(image)
    regular, bold = ImageFont.truetype(FONT, 30), ImageFont.truetype(BOLD, 48)
    draw.rectangle((0, 0, 720, 12), fill='#60e5cf')
    draw.text((42, 50), 'TROVOX GLOB', font=ImageFont.truetype(BOLD, 31), fill='#60e5cf')
    draw.text((42, 112), 'GLOBAL RAIN NOWCASTING', font=ImageFont.truetype(BOLD, 20), fill='#ffbe61')
    draw.text((42, 190), item['nome'], font=bold, fill='white')
    draw.text((42, 250), item['pais'], font=regular, fill='#bed3e4')
    draw.rounded_rectangle((38, 340, 682, 790), radius=24, fill='#142b3e')
    draw.text((72, 390), 'RAIN NOW', font=ImageFont.truetype(BOLD, 26), fill='#60e5cf')
    draw.text((72, 455), f"{item['chuva_atual_mm']:.1f} mm", font=ImageFont.truetype(BOLD, 78), fill='white')
    draw.text((72, 600), '6-HOUR RAIN CHANCE', font=ImageFont.truetype(BOLD, 26), fill='#60e5cf')
    draw.text((72, 660), f"{item['probabilidade_6h']}%", font=ImageFont.truetype(BOLD, 78), fill='white')
    draw.rounded_rectangle((38, 845, 682, 1135), radius=24, fill='#142b3e')
    y = 885
    for line in ('Automated estimate based on Open-Meteo.', 'Not an official warning.', 'Check your local weather service.'):
        draw.text((70, y), line, font=regular, fill='#dceaf4'); y += 65
    draw.text((42, 1200), 'Source: Open-Meteo • UTC update', font=ImageFont.truetype(FONT, 19), fill='#bed3e4')
    image.save(directory / 'card.png')
    subprocess.run(['ffmpeg', '-y', '-v', 'error', '-loop', '1', '-i', str(directory / 'card.png'),
                    '-i', str(directory / 'voz.mp3'), '-c:v', 'libx264', '-pix_fmt', 'yuv420p',
                    '-r', '25', '-c:a', 'aac', '-shortest', str(directory / 'short.mp4')], check=True, timeout=180)
