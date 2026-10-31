"""Evidence-led scene production, resumable on disk, using the approved template."""
from dataclasses import asdict
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from pathlib import Path
import hashlib
import json
import os
import re
import subprocess
import textwrap

from .segments import Segment, join_audio, save_plan
from .directed_scenes import capture_segments
from .lightning_agent import LightningAgentClient
from .speech import narrate
from .official import render_official
from .wardrobe import wardrobe_for_job
from .forecast_policy import ECENS_EDITORIAL_NAME, LIGHTNING_METHOD, validate_forecasts, validate_forecast_text, narration_view

ROOT = Path(__file__).resolve().parents[2]
BRIEF = ROOT/'prompts/boletim-meteorologico.md'


def card(path, title, lines):
    from PIL import Image, ImageDraw, ImageFont
    im=Image.new('RGB',(1440,810),'#102337');d=ImageDraw.Draw(im)
    f='/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf'
    d.rectangle((50,50,1390,56),fill='#65e0d0')
    d.text((60,90),title,font=ImageFont.truetype(f,38),fill='white')
    y=190
    for line in lines:
        for row in textwrap.wrap(line,64):
            d.text((60,y),row,font=ImageFont.truetype(f,29),fill='#dae7ef');y+=46
        y+=24
    im.save(path)


def stamp(s):
    from PIL import Image,ImageDraw,ImageFont
    im=Image.open(s.image).convert('RGB');d=ImageDraw.Draw(im)
    font='/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf'
    d.rectangle((0,0,1440,75),fill='#102337')
    d.text((22,7),s.title,font=ImageFont.truetype(font,27),fill='white')
    period=s.metadata.get('period','Consulte a validade na legenda')
    if s.category in ('nowcasting','observacao','alagamento','extrapolacao'):
        n=s.metadata.get('nowcast') or {}
        period=f"Raios até {n.get('raios_ate','não informado')} | Nuvens: {n.get('nuvens_de','não informado')}"
    if s.category in ('previsao','destaque') and s.view in ('deterministico','risco','probabilidade'):
        period = LIGHTNING_METHOD + ' | ' + period
    d.text((22,43),textwrap.shorten(period,145),font=ImageFont.truetype(font,17),fill='#b9d6e2')
    im.save(s.image)


def plain(text):
    text=re.sub(r'\*\*|__|`|^#{1,6}\s*','',text,flags=re.M)
    return re.sub(r'\s+',' ',text).strip()


def produce(directory: Path, *, api='https://lightning-agent.onrender.com', title='Boletim meteorológico | América do Sul', capture_only=False, app_url=None, presentation_at=None):
    directory=directory.resolve();directory.mkdir(parents=True,exist_ok=True)
    profile=os.environ.get('VIDEO_PROFILE','full').strip().lower()
    if profile not in {'full','balanced','lite'}:
        raise ValueError('VIDEO_PROFILE deve ser full, balanced ou lite')
    selected_wardrobe = wardrobe_for_job(directory, presentation_at)
    client=LightningAgentClient(api,api+'/app/')
    prompt=BRIEF.read_text()
    (directory/'prompt-utilizado.md').write_text(prompt)
    discovery=directory/'destaques.json'
    # The emergency short profile avoids local discovery. The balanced remote
    # bulletin keeps the Brazilian lightning highlights and the nowcasting arc.
    if profile == 'lite':
        places=[]
    elif discovery.is_file():
        places=json.loads(discovery.read_text())
    else:
        selection=client.perguntar('Selecione de dois a três municípios ou regiões brasileiras com maior potencial previsto de descargas elétricas pela IA com parâmetros convectivos do ECENS. Use somente a evidência atual. Responda SOMENTE JSON {"locais":[{"nome":"Cidade, UF","fenomeno":"raios","motivo":"evidência curta"}]}. Não invente. Se insuficiente, use os locais confirmados disponíveis.')
        (directory/'selecao-agente.json').write_text(json.dumps(selection,ensure_ascii=False,indent=2))
        try:
            options=json.loads(selection['resposta'].strip().removeprefix('```json').removesuffix('```')).get('locais',[])[:3]
        except (ValueError,AttributeError): options=[]
        places=[]
        for option in options:
            result=client.perguntar('Localize e mostre a previsão de raios da IA com parâmetros convectivos do ECENS para '+option['nome']+'. Use o local geográfico estruturado na resposta e confirme o estado, sem inventar coordenadas.')
            local=result.get('local')
            if local and local.get('lat') is not None and local.get('lon') is not None:
                places.append({'place':local,'evidence':result,'selection':option})
        discovery.write_text(json.dumps(places,ensure_ascii=False,indent=2))
    specs=[
        Segment('01-chuva','Chuva prevista | ECMWF (ECENS)','previsao','chuva-prevista','ecens'),
        Segment('02-ecens','Raios previstos | IA e parâmetros convectivos do ECMWF (ECENS)','previsao','deterministico','ecens'),
        Segment('03-risco','Risco de raios | IA e parâmetros convectivos do ECMWF (ECENS)','previsao','risco','ecens'),
    ]
    for i,p in enumerate(places):
        specs.append(Segment(f'04-local-{i+1}','Probabilidade de raios | '+p['place']['nome'],'destaque','probabilidade','ecens',place=p['place'],evidence=p))
    specs += [
        Segment('05-agora','Condições atuais | Nowcasting','nowcasting','severidade','monitoramento'),
        Segment('06-observado','Atividade elétrica observada','observacao','agora','monitoramento'),
        Segment('07-alagamento','Potencial de alagamento | Curtíssimo prazo','alagamento','inundacoes','monitoramento'),
        Segment('08-extrap-0','Extrapolação de raios e nuvens | Ponto inicial','extrapolacao','extrapolacao','monitoramento',horizon=0),
        Segment('09-extrap-60','Extrapolação | +60 minutos','extrapolacao','extrapolacao','monitoramento',horizon=60),
        Segment('10-extrap-120','Extrapolação | +120 minutos','extrapolacao','extrapolacao','monitoramento',horizon=120),
        Segment('11-recomendacoes','Riscos e recomendações','recomendacao','summary'),
    ]
    if profile == 'balanced':
        keep={'01-chuva','02-ecens','03-risco','05-agora','06-observado',
              '07-alagamento','08-extrap-0','09-extrap-60','10-extrap-120',
              '11-recomendacoes'}
        specs=[s for s in specs if s.id in keep]
        print('Perfil equilibrado: previsões ECENS, até três destaques brasileiros e sequência completa de nowcasting.',flush=True)
    elif profile == 'lite':
        keep={'01-chuva','02-ecens','03-risco','11-recomendacoes'}
        specs=[s for s in specs if s.id in keep]
        print('Perfil leve: 4 cenas essenciais, sem consultas locais ou nowcasting.',flush=True)
    captures=directory/'capturas.json'
    if captures.is_file():
        specs=[Segment(**s) for s in json.loads(captures.read_text())]
    else:
        print('Capturando produtos oficiais...',flush=True)
        capture_segments(app_url or api+'/app/',specs,directory/'cenas')
        for s in specs:
            if s.view=='summary' or not s.available:
                image=directory/'cenas'/f'{s.id}.png'
                if s.view=='summary':
                    card(image,'Proteção durante tempestades',[
                        'Raios: procure uma construção fechada e segura.',
                        'Evite áreas abertas, árvores, praias e piscinas.',
                        'Alagamentos: não atravesse vias inundadas.',
                        'Mantenha distância de rios em elevação.',
                        'Acompanhe os avisos da Defesa Civil.'])
                else:
                    card(image,s.title,['Visualização indisponível nesta consulta.',
                        'Este trecho não apresenta áreas ou ocorrências confirmadas.',
                        'Consulte os avisos oficiais da Defesa Civil.'])
                s.image=str(image)
            else:stamp(s)
            print(s.id, 'disponível' if s.available else s.metadata.get('error'),flush=True)
        save_plan(specs,captures)
    validate_forecasts(specs)
    if capture_only:return specs
    audios=directory/'audios';audios.mkdir(exist_ok=True)
    for s in specs:
        textfile=directory/'cenas'/f'{s.id}.txt'
        evidence_file=directory/'cenas'/f'{s.id}-agente.json'
        if textfile.is_file():
            s.narration=textfile.read_text()
        elif not s.available:
            s.narration=f'{s.title}. Não foi possível validar esta visualização nesta consulta. Por isso, não vamos indicar localidades ou ocorrências com base nessa camada.'
            textfile.write_text(s.narration)
        else:
            presentation_date=(presentation_at or datetime.now(timezone.utc)).astimezone(ZoneInfo('America/Belem')).strftime('%d/%m/%Y')
            directives={
                '01-chuva':f'Abra com uma introdução jornalística curta usando a data {presentation_date}. Diga que a prioridade é informar a população para prevenção de riscos, proteção de vidas e redução dos impactos de eventos extremos. Em seguida, fale somente de chuva prevista exclusivamente pelo {ECENS_EDITORIAL_NAME} para América do Sul, citando os acumulados e regiões que estão visíveis na camada. A camada está disponível: nunca diga que não há acumulados, que os valores estão indisponíveis ou que não é possível avaliar a chuva quando a legenda/mapa exibir valores. Não associe alagamento confirmado.',
                '02-ecens':f'Explique que os raios são previstos pelo modelo de inteligência artificial usando parâmetros convectivos do {ECENS_EDITORIAL_NAME}, não uma saída direta de raios do modelo meteorológico. Para América do Sul, destacando países/regiões confirmados. Não use raios observados.',
                '03-risco':f'Explique as áreas de risco de raios geradas pela IA com parâmetros convectivos do {ECENS_EDITORIAL_NAME}; não declare severidade ou granizo com base nessa camada.',
                '05-agora':'Comece: Agora passamos das previsões para as condições atuais monitoradas. Explique os polígonos de severidade no Brasil sustentados pelos dados, sem radar na imagem.',
                '06-observado':'Descreva atividade elétrica observada no Brasil confirmada pelos dados e horário do detector, sem misturar com previsão.',
                '07-alagamento':'Comece exatamente: Esta é uma previsão de risco de alagamento para as condições atuais, baseada no monitoramento e na análise de curtíssimo prazo. Não diga que alagou. Se não houver dados locais confirmados, diga isso.',
                '08-extrap-0':'Diga exatamente: Esta é uma extrapolação da atividade de raios para as próximas duas horas, indicando a possível evolução e deslocamento das áreas de atividade elétrica. Acrescente que a camada combina raios e nuvens, e que este quadro mostra o ponto inicial, não uma previsão ECENS.',
                '09-extrap-60':'A imagem é de +60 minutos. Explique que são áreas deslocadas pelo movimento medido, sem garantir formação ou enfraquecimento. Não invente direção ou localidades sem evidência.',
                '10-extrap-120':'A imagem é de +120 minutos. Enfatize incerteza e natureza de extrapolação, não uma ocorrência confirmada nem previsão ECENS. Não afirme que a intensidade permanecerá igual.',
                '11-recomendacoes':'Finalize com recomendações práticas de raios e alagamentos, relacionadas às regiões antes identificadas quando confirmadas. Não atravesse vias alagadas; abrigo fechado; evite árvores, áreas abertas, praias e piscinas; acompanhe a Defesa Civil.',
            }
            instruction=directives.get(s.id,f'Explique somente a probabilidade de raios (%) da IA com parâmetros convectivos do {ECENS_EDITORIAL_NAME} para o local estruturado informado. Apresente este local como um dos principais pontos brasileiros de maior potencial de descargas elétricas na previsão. Não mencione contagens ou acumulados de raios. Confirme nome/estado e não use uma cidade diferente.')
            question=(f'Siga as regras do prompt editorial salvo:\n{prompt.split("## Regras de evidência")[1].split("## Sequência editorial")[0]}\n\nAGORA produza SOMENTE a fala da cena {s.id}, sem títulos, markdown, JSON ou listas. '
                'Use português brasileiro natural, 2 frases e no máximo 45 palavras, exceto as frases obrigatórias. Não repita outras seções. '
                f'{instruction} Camada selecionada: {s.view}. Probabilidade em porcentagem exige probabilidade; quantidade/acumulado de raios exige deterministico. Nunca misture as duas métricas numa cena.\nA imagem validada contém estes metadados: '+json.dumps({k:v for k,v in s.metadata.items() if k in ('view','product','period','legend','polygon_count','bounds')},ensure_ascii=False)+
                '\nDestaque local/evidências: '+json.dumps(s.evidence,ensure_ascii=False))
            result=client.perguntar(question)
            evidence_file.write_text(json.dumps(result,ensure_ascii=False,indent=2))
            s.evidence['narrator']=result
            s.narration=plain(result['resposta']);textfile.write_text(s.narration)
        expected_view=narration_view(s)
        if s.available and expected_view!=s.view:
            previous_view=s.view
            s.view=expected_view
            label='Probabilidade de raios' if expected_view=='probabilidade' else 'Quantidade prevista de raios'
            s.title=label+' | '+(s.place['nome'] if s.place else 'IA com parâmetros convectivos do ECMWF (ECENS)')
            capture_segments(app_url or api+'/app/',[s],directory/'cenas')
            if not s.available:
                save_plan(specs,directory/'plano-cenas.json')
                raise RuntimeError(f'{s.id}: não foi possível capturar {expected_view}; não usar a imagem anterior')
            s.metadata['layer_adjustment']={'previous':previous_view,'selected':expected_view,'reason':'métrica da narração'}
            stamp(s)
            save_plan(specs,captures)
        validate_forecast_text(s)
        if any(x in s.narration.lower() for x in ('groq não respondeu','muitas perguntas','tente de novo')):
            raise RuntimeError(f'{s.id}: resposta técnica não pode ser narrada')
        if evidence_file.is_file():
            s.evidence['narrator_raw'] = json.loads(evidence_file.read_text())
        s.evidence['final_text_sha256'] = hashlib.sha256(s.narration.encode()).hexdigest()
        print('Narração:',s.id,s.narration,flush=True)
        raw=audios/f'{s.id}-raw.wav';final=audios/f'{s.id}.wav'
        rate=float(os.environ.get('NARRATION_SPEED','0.90'))
        fingerprint = hashlib.sha256((s.narration + os.environ.get('EDGE_TTS_VOICE','pt-BR-FranciscaNeural') + str(rate)).encode()).hexdigest()
        cache = audios/f'{s.id}.sha256'
        if final.is_file() and cache.is_file() and cache.read_text() != fingerprint:
            final.unlink()
            if raw.is_file():raw.unlink()
        if not final.is_file():
            if not raw.is_file():narrate(s.narration,raw)
            rate=float(os.environ.get('NARRATION_SPEED','0.90'))
            subprocess.run(['ffmpeg','-y','-v','error','-i',str(raw),'-af',f'atempo={rate}',
                '-ar','16000','-ac','1',str(final)],check=True)
        cache.write_text(fingerprint)
        s.audio=str(final)
        save_plan(specs,directory/'plano-cenas.json')
    final_audio=directory/'narracao-final.wav'
    total=join_audio(specs,final_audio)
    save_plan(specs,directory/'plano-cenas.json')
    (directory/'roteiro.md').write_text('\n\n'.join(f'## {s.title} ({s.start:.2f}–{s.end:.2f}s)\n\n{s.narration}' for s in specs))
    (directory/'evidencias.json').write_text(json.dumps([{'id':s.id,'metadata':s.metadata,'agent':s.evidence} for s in specs],ensure_ascii=False,indent=2))
    output=directory/'boletim.mp4'
    print('Sincronizando e montando',total,'segundos',flush=True)
    render_official([Path(s.image) for s in specs],final_audio,output,title=title,
        subtitle='Previsão, monitoramento e extrapolação | Validade indicada em cada cena',
        scene_durations=[s.duration for s in specs],narration_final=True,
        presenter_source=Path(selected_wardrobe['file']))
    (directory/'revisao.md').write_text(f'# Revisão da geração\n\nDuração: {total:.2f}s.\n'
        f'Prompt SHA-256: {hashlib.sha256(prompt.encode()).hexdigest()}\n'
        'Tempos calculados pelos áudios finais de cada cena, alinhados a 25 fps.\n'
        'Sem camada de radar. Lábios sincronizados após o ajuste de velocidade.\n'
        'Metadados e respostas do agente preservados para revisão editorial.\n\n'
        +'\n'.join(f'- {s.id}: '+('captura disponível' if s.available else 'indisponível; ausência declarada') for s in specs)+'\n')
    print(output,flush=True)
    return output
