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
from .speech import prepare_scene_audios
from .tourism import tourism_direction, tourism_evidence
from .bulletin_context import brazilian_highlights, add_time_reference, local_recommendations, readable_times
from .editorial import regional_scene_direction, validate_scene_evidence
from .official import render_official
from .wardrobe import wardrobe_for_job
from .forecast_policy import ECENS_EDITORIAL_NAME, LIGHTNING_METHOD, validate_forecasts, validate_forecast_text, narration_view

ROOT = Path(__file__).resolve().parents[2]
BRIEF = ROOT/'prompts/boletim-meteorologico.md'
CLOSING_CTA = 'Inscreva-se no canal TROVOX TEMPO e ative o sino para receber novos avisos e atualizações. Curta o vídeo e compartilhe com amigos, familiares e grupos para que as informações meteorológicas cheguem a mais pessoas.'


def channel_narration(text, scene_id):
    """Reserve the channel's single spoken name for the closing CTA."""
    text = text.replace(CLOSING_CTA, '').strip()
    text = re.sub(r'\b(?:trovox\s+tempo|lightning\s+agent)\b', 'nosso canal', text, flags=re.I)
    if scene_id == '11-recomendacoes':
        text = text.rstrip() + '\n\n' + CLOSING_CTA
    return text


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
    period=s.metadata.get('period','Consulte a validade na legenda')
    if s.category in ('nowcasting','observacao','alagamento','extrapolacao'):
        n=s.metadata.get('nowcast') or {}
        period=f"Raios até {n.get('raios_ate','não informado')} | Nuvens: {n.get('nuvens_de','não informado')}"
    if s.category in ('previsao','destaque') and s.view in ('deterministico','risco','probabilidade'):
        period = LIGHTNING_METHOD + ' | ' + period
    period = readable_times(period, include_brasilia=True)
    lines = textwrap.wrap(period, width=140) or ['']
    d.rectangle((0,0,1440,55+22*len(lines)),fill='#102337')
    d.text((22,7),s.title,font=ImageFont.truetype(font,27),fill='white')
    for i, line in enumerate(lines):
        d.text((22,43+22*i),line,font=ImageFont.truetype(font,17),fill='#b9d6e2')
    im.save(s.image)


def plain(text):
    text=re.sub(r'\*\*|__|`|^#{1,6}\s*','',text,flags=re.M)
    return re.sub(r'\s+',' ',text).strip()


def fallback_narration(scene, presentation_date):
    """Safe continuity copy when the public editorial agent is rate-limited.

    It intentionally names no unverified city, value, alert or movement. The
    captured official layer remains on screen and the bulletin can complete.
    """
    editorial=scene.evidence.get('editorial',{})
    rain=[x for x in editorial.get('chuva',{}).get('regioes',[]) if str(x.get('pais','')).casefold() in ('brasil','brazil')][:3]
    lightning=editorial.get('raios',{}).get('regioes',[])[:3]
    def names(rows):
        return ', '.join(f"{x.get('cidade')} ({x.get('pais')})" for x in rows if x.get('cidade'))
    rain_names, lightning_names=names(rain), names(lightning)
    copy={
        '01-chuva':f'Hoje, {presentation_date}, a prioridade é informar a população para prevenção de riscos, proteção de vidas e redução dos impactos de eventos extremos. A chuva prevista pelo {ECENS_EDITORIAL_NAME} destaca {rain_names}; consulte a legenda para os acumulados e o período válido.' if rain_names else f'Hoje, {presentation_date}, a prioridade é informar a população para prevenção de riscos, proteção de vidas e redução dos impactos de eventos extremos. A chuva prevista pelo {ECENS_EDITORIAL_NAME} está apresentada nesta camada; consulte a legenda para os acumulados e o período válido.',
        '05-agora':'Agora passamos das previsões para as condições atuais monitoradas. Este quadro mostra as áreas analisadas no momento; acompanhe os avisos oficiais da Defesa Civil.',
        '06-observado':'Este quadro apresenta a atividade elétrica observada no Brasil no horário indicado. Observação e previsão são produtos diferentes; acompanhe a atualização mais recente.',
        '07-alagamento':'Esta é uma previsão de risco de alagamento para as condições atuais, baseada no monitoramento e na análise de curtíssimo prazo. Não atravesse vias inundadas e acompanhe a Defesa Civil.',
        '08-extrap-0':'Esta é uma extrapolação da atividade de raios para as próximas duas horas. A camada combina raios e nuvens e este quadro mostra o ponto inicial, não uma previsão ECENS.',
        '09-extrap-60':'Esta imagem mostra uma extrapolação para sessenta minutos baseada no movimento medido. Ela indica possível deslocamento das áreas, sem garantir formação ou enfraquecimento.',
        '10-extrap-120':'Esta imagem mostra uma extrapolação para cento e vinte minutos. A incerteza aumenta com o tempo, portanto acompanhe as atualizações e os avisos oficiais.',
        '11-recomendacoes':'Durante tempestades, procure abrigo em construção fechada, evite árvores, áreas abertas, praias e piscinas. Não atravesse vias alagadas e acompanhe a Defesa Civil.',
    }
    if scene.id in ('05-agora', '07-alagamento'):
        product = 'severidade' if scene.id == '05-agora' else 'potencial de alagamento'
        count = scene.metadata.get('polygon_count', 0)
        if count:
            return (f'O mapa apresenta áreas classificadas de {product} na área exibida. '
                    'A captura não permite atribuir todas essas áreas a cidades e regiões com segurança. '
                    'Acompanhe as classes da legenda e os avisos da Defesa Civil.')
        return (f'Não foi possível confirmar a distribuição regional de {product} nesta captura. '
                'Isso não permite concluir ausência de risco nas regiões brasileiras. '
                'Acompanhe as atualizações e os avisos da Defesa Civil.')
    if scene.id == '06-observado':
        observed = scene.evidence.get('observed', {})
        rows = [x for x in observed.get('regioes', []) if x.get('pais') == 'Brasil' and x.get('cidade') and isinstance(x.get('raios'), (int, float))][:3]
        if rows:
            highlights = '; '.join(f"perto de {x['cidade']}, {x['raios']} descargas" for x in rows)
            return f"Entre os destaques de raios observados estão {highlights}. As contagens são de áreas próximas a essas cidades, na janela de {observed['inicio']} a {observed['fim']}."
    if scene.category in ('previsao', 'destaque') and scene.view in ('deterministico', 'probabilidade', 'risco'):
        metric = {'deterministico': 'a quantidade prevista de raios', 'probabilidade': 'a probabilidade de raios em porcentagem', 'risco': 'as áreas de risco de raios'}[scene.view]
        local_names = brazilian_highlights(scene)
        location = f" na área de {scene.place['nome']}" if scene.place and scene.place.get('nome') else ('; entre os destaques brasileiros estão ' + ', '.join(local_names) if local_names else '')
        intro = f"Entre os lugares de destaque está {scene.place['nome']}. " if scene.place and scene.place.get('nome') else ''
        return intro + f'Previsão de Raios: este mapa apresenta {metric}{location} para o período indicado. Acompanhe a distribuição e as classes exibidas na legenda.'
    return copy.get(scene.id,'Consulte a legenda e os avisos oficiais para acompanhar esta condição meteorológica.')


def produce(directory: Path, *, api='https://lightning-agent.onrender.com', title='Boletim meteorológico | Brasil', capture_only=False, app_url=None, presentation_at=None):
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
    editorial={}
    try:
        editorial=client.destaques_editoriais()
        (directory/'destaques-ecens.json').write_text(json.dumps(editorial,ensure_ascii=False,indent=2))
    except Exception as exc:
        (directory/'destaques-ecens-erro.json').write_text(json.dumps({'error':str(exc)},ensure_ascii=False,indent=2))
    if editorial.get('brasil_maior_atividade_raios'):
        places=[{'place':{'nome':f"{x['cidade']}, {x['pais']}",'lat':x['lat'],'lon':x['lon']},'evidence':x}
                for x in editorial['brasil_maior_atividade_raios'][:3]]
    elif profile == 'lite':
        places=[]
    elif discovery.is_file():
        places=json.loads(discovery.read_text())
    else:
        selection_prompt='Selecione de dois a três municípios ou regiões brasileiras com maior potencial previsto de descargas elétricas pela IA com parâmetros convectivos do ECENS. Use somente a evidência atual. Responda SOMENTE JSON válido, sem markdown nem texto adicional: {"locais":[{"nome":"Cidade, UF","fenomeno":"raios","motivo":"evidência curta"}]}. Não invente. Se insuficiente, use os locais confirmados disponíveis.'
        try:
            selection=client.perguntar(selection_prompt)
        except RuntimeError as exc:
            selection={'resposta':'', 'error':str(exc)}
        (directory/'selecao-agente.json').write_text(json.dumps(selection,ensure_ascii=False,indent=2))
        try:
            options=json.loads(selection['resposta'].strip().removeprefix('```json').removesuffix('```')).get('locais',[])[:3]
        except (ValueError,AttributeError): options=[]
        if not options and not selection.get('error'):
            try:
                selection=client.perguntar(selection_prompt+' A resposta anterior não pôde ser lida; devolva somente o JSON solicitado.')
            except RuntimeError as exc:
                selection={'resposta':'', 'error':str(exc)}
            (directory/'selecao-agente-tentativa-2.json').write_text(json.dumps(selection,ensure_ascii=False,indent=2))
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
        Segment('01-chuva','Chuva prevista | ECMWF (ECENS)','previsao','chuva-prevista','ecens',evidence={'editorial':editorial}),
        Segment('02-ecens','Previsão de Raios','previsao','deterministico','ecens',evidence={'editorial':editorial}),
        Segment('03-risco','Previsão de Raios | Áreas de risco','previsao','risco','ecens',evidence={'editorial':editorial}),
    ]
    for i,p in enumerate(places):
        specs.append(Segment(f'04-local-{i+1}','Probabilidade de raios | '+p['place']['nome'],'destaque','probabilidade','ecens',place=p['place'],evidence={**p,'editorial':editorial}))
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
        specs=[s for s in specs if s.id in keep or s.id.startswith('04-local-')]
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
    observed = {}
    if any(s.id == '06-observado' and s.available for s in specs):
        try:
            observed = client.resumo_observado()
            (directory/'observado-utilizado.json').write_text(json.dumps(observed,ensure_ascii=False,indent=2))
        except Exception as exc:
            (directory/'observado-erro.json').write_text(json.dumps({'error':str(exc)},ensure_ascii=False))
    audios=directory/'audios';audios.mkdir(exist_ok=True)
    spoken_periods = set()
    for s in specs:
        if s.id == '06-observado':
            s.evidence['observed'] = observed
        textfile=directory/'cenas'/f'{s.id}.txt'
        evidence_file=directory/'cenas'/f'{s.id}-agente.json'
        presentation_date=(presentation_at or datetime.now(timezone.utc)).astimezone(ZoneInfo('America/Belem')).strftime('%d/%m/%Y')
        if textfile.is_file():
            s.narration=textfile.read_text()
        elif not s.available:
            s.narration=f'{s.title}. Não foi possível validar esta visualização nesta consulta. Por isso, não vamos indicar localidades ou ocorrências com base nessa camada.'
            textfile.write_text(s.narration)
        else:
            directives={
                '01-chuva':f'Abra com uma introdução jornalística curta usando a data {presentation_date}. Diga que a prioridade é informar a população para prevenção de riscos, proteção de vidas e redução dos impactos de eventos extremos. Na primeira menção, escreva explicitamente “{ECENS_EDITORIAL_NAME}”. Em seguida, fale somente de chuva prevista por esse modelo priorizando o Brasil, citando os acumulados e regiões que estão visíveis na camada. A lista de cidades é parcial e não permite afirmar ausência de chuva em nenhuma região, especialmente no Centro-Oeste. Se uma região não estiver na lista, declare apenas que faltou detalhamento regional. A camada está disponível: nunca diga que não há acumulados, que os valores estão indisponíveis ou que não é possível avaliar a chuva quando a legenda/mapa exibir valores. Não associe alagamento confirmado.',
                '02-ecens':'Comece com Previsão de Raios. Fale exclusivamente da quantidade prevista de raios na camada determinística, ou da probabilidade de raios em porcentagem se a camada selecionada for probabilidade. Destaque primeiro cidades e regiões brasileiras confirmadas; use a América do Sul apenas como contexto breve. Não fale de chuva, acumulados de precipitação, ECENS, ECMWF, parâmetros convectivos ou inteligência artificial. Não use raios observados.',
                '03-risco':'Apresente as áreas de risco de raios e as classes da legenda. Destaque somente regiões confirmadas. Não fale de chuva, modelos, inteligência artificial ou parâmetros convectivos; não use percentuais nesta cena nem declare granizo com base nessa camada.',
                '05-agora':'Consulte os polígonos atuais e destaque as localidades e regiões brasileiras com maior severidade confirmada. Comece: Agora passamos das previsões para as condições atuais monitoradas. Explique os polígonos de severidade no Brasil sustentados pelos dados, sem radar na imagem.',
                '06-observado':'Consulte o resumo de raios observados e destaque os locais com mais descargas por região brasileira, com contagens e janela do detector quando disponíveis. Não atribua contagens de uma área inteira a uma cidade. Só mencione previsão anterior com comparação explicitamente comprovada para o mesmo local e período. Não afirme que o evento ocorreu sem previsão prévia, pois essa comparação não é sustentada por esta camada.',
                '07-alagamento':'Destaque por região os locais com maior potencial de alagamento confirmado pela camada, sem inventar ocorrências. Comece exatamente: Esta é uma previsão de risco de alagamento para as condições atuais, baseada no monitoramento e na análise de curtíssimo prazo. Não diga que alagou. Se não houver dados locais confirmados, diga isso.',
                '08-extrap-0':'Diga exatamente: Esta é uma extrapolação da atividade de raios para as próximas duas horas, indicando a possível evolução e deslocamento das áreas de atividade elétrica. Acrescente que a camada combina raios e nuvens, e que este quadro mostra o ponto inicial, não uma previsão ECENS.',
                '09-extrap-60':'A imagem é de +60 minutos. Explique que são áreas deslocadas pelo movimento medido, sem garantir formação ou enfraquecimento. Não invente direção ou localidades sem evidência.',
                '10-extrap-120':'A imagem é de +120 minutos. Enfatize incerteza e natureza de extrapolação, não uma ocorrência confirmada nem previsão ECENS. Não afirme que a intensidade permanecerá igual.',
                '11-recomendacoes':'O canal se chama TROVOX TEMPO. A chamada para inscrição, sino, curtida e compartilhamento será acrescentada automaticamente após esta fala; produza somente as recomendações meteorológicas. Finalize com recomendações práticas de raios e alagamentos, relacionadas às regiões antes identificadas quando confirmadas. Não atravesse vias alagadas; abrigo fechado; evite árvores, áreas abertas, praias e piscinas; acompanhe a Defesa Civil.',
            }
            instruction=directives.get(s.id,f'Explique somente a probabilidade de raios (%) para o local estruturado informado. Use o nome Previsão de Raios, sem mencionar modelos, inteligência artificial, parâmetros convectivos ou chuva. Diga apenas: Entre os lugares de destaque está, seguido do nome deste local. Não o classifique como um dos maiores riscos sem comparação comprovada. Não mencione contagens ou acumulados de raios. Confirme nome/estado e não use uma cidade diferente.')
            regional_direction = regional_scene_direction(s.id) + ' ' + tourism_direction(s)
            question=(f'Siga as regras do prompt editorial salvo:\n{prompt.split("## Regras de evidência")[1].split("## Sequência editorial")[0]}\n\nAGORA produza SOMENTE a fala da cena {s.id}, sem títulos, markdown, JSON ou listas. '
                'Não pronuncie o nome do canal nesta cena; ele será dito uma única vez na CTA final. Vá direto à informação meteorológica. Use português brasileiro natural, dinâmico e profissional. Não narre datas de validade nem horários nesta resposta: o gerador acrescentará a referência temporal apenas quando necessário, sem repetir períodos iguais. Faça destaques concretos coerentes com esta imagem; não repita outras seções. '
                'O foco do boletim é o Brasil, suas cidades, estados e cinco regiões. A América do Sul serve apenas como contexto breve. Nunca cite localidades, países, dados ou fenômenos de outros continentes. '
                f'{regional_direction} {instruction} Camada selecionada: {s.view}. Probabilidade em porcentagem exige probabilidade; quantidade/acumulado de raios exige deterministico. Nunca misture as duas métricas numa cena.')
            narration_evidence = {
                'scene_id': s.id, 'view': s.view, 'local': s.place,
                'metadata': {k:v for k,v in s.metadata.items() if k in
                    ('view','product','period','legend','forecast_window','polygon_count','polygon_evidence','analysis_bounds','nowcast','bounds')},
                'destaques': s.evidence,
                'lugares_turisticos_com_evidencia': tourism_evidence(s),
            }
            try:
                result=client.narrar(question, narration_evidence)
            except RuntimeError as exc:
                s.evidence['narrator_fallback']={'reason':str(exc)}
                result={'resposta':fallback_narration(s,presentation_date),'fallback':True}
            evidence_file.write_text(json.dumps(result,ensure_ascii=False,indent=2))
            s.evidence['narrator']=result
            s.narration=plain(result['resposta']);textfile.write_text(s.narration)
        if s.id == '11-recomendacoes':
            contextual_advice = local_recommendations(specs)
            if contextual_advice:
                s.narration = contextual_advice
        try:
            validate_scene_evidence(s)
        except ValueError as exc:
            s.evidence['editorial_correction'] = str(exc)
            s.narration = fallback_narration(s, presentation_date)
            validate_scene_evidence(s)
            textfile.write_text(s.narration)
        expected_view=narration_view(s)
        if s.available and expected_view!=s.view:
            previous_view=s.view
            s.view=expected_view
            label='Probabilidade de raios' if expected_view=='probabilidade' else 'Quantidade prevista de raios'
            s.title=label+' | '+(s.place['nome'] if s.place else 'Previsão de Raios')
            capture_segments(app_url or api+'/app/',[s],directory/'cenas')
            if not s.available:
                save_plan(specs,directory/'plano-cenas.json')
                raise RuntimeError(f'{s.id}: não foi possível capturar {expected_view}; não usar a imagem anterior')
            s.metadata['layer_adjustment']={'previous':previous_view,'selected':expected_view,'reason':'métrica da narração'}
            stamp(s)
            save_plan(specs,captures)
        try:
            validate_forecast_text(s)
        except ValueError:
            # Do not let an editorial omission turn a complete capture into a
            # failed video. The fallback preserves the selected metric.
            # Keep fallback copy aligned with the captured lightning metric.
            if s.category not in ('previsao', 'destaque') or s.view not in ('deterministico', 'probabilidade', 'risco') or not s.available:
                raise
            s.narration=fallback_narration(s,presentation_date)
            textfile.write_text(s.narration)
            validate_forecast_text(s)
        add_time_reference(s, spoken_periods)
        validate_scene_evidence(s)
        s.narration = readable_times(channel_narration(s.narration, s.id), include_brasilia=True)
        textfile.write_text(s.narration)
        if any(x in s.narration.lower() for x in ('groq não respondeu','muitas perguntas','tente de novo')):
            raise RuntimeError(f'{s.id}: resposta técnica não pode ser narrada')
        if evidence_file.is_file():
            s.evidence['narrator_raw'] = json.loads(evidence_file.read_text())
        s.evidence['final_text_sha256'] = hashlib.sha256(s.narration.encode()).hexdigest()
        print('Narração:',s.id,s.narration,flush=True)
        save_plan(specs,directory/'plano-cenas.json')
    prepare_scene_audios(specs, audios, workers=int(os.environ.get('VIDEO_TTS_WORKERS', '2')))
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
