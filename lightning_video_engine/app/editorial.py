"""Regional, evidence-led editorial brief for South America lightning videos."""

REGIONAL_QUESTIONS = (
    "Em até duas frases, descreva onde há raios observados agora na América do Sul, por regiões e países. Não invente locais.",
    "Em até duas frases, diga onde há maior severidade agora no Brasil, agrupando Norte, Nordeste, Centro-Oeste, Sudeste e Sul. Se não houver confirmação, diga isso.",
    "Em até duas frases, diga onde existe potencial de alagamento agora no Brasil. Trate como potencial, não como inundação confirmada.",
    "Em até três frases, resuma a previsão de raios e chuva de hoje para Norte, Nordeste, Centro-Oeste, Sudeste e Sul do Brasil, e Argentina ou outros países sul-americanos quando os dados confirmarem.",
    "Em uma frase, dê uma recomendação geral de segurança para raios e chuva forte, sem criar alertas oficiais.",
)


def pauta_regional(client) -> str:
    """Ask the public Lightning Agent once per editorial subject in one conversation."""
    session_id = None
    answers = []
    for question in REGIONAL_QUESTIONS:
        result = client.perguntar(question, session_id)
        session_id = result.get("session_id") or session_id
        answers.append(result["resposta"].strip())
    return " ".join(answers)


BRAZIL_REGIONS = ('Sul', 'Sudeste', 'Nordeste', 'Centro-Oeste', 'Norte')


def regional_scene_direction(scene_id):
    """Budget national coverage separately from local and monitoring scenes."""
    if scene_id in ('05-agora', '06-observado', '07-alagamento'):
        product = {
            '05-agora': 'tempo severo identificado pelos polígonos de monitoramento; não deduza severidade apenas da quantidade de raios',
            '06-observado': 'locais com mais descargas elétricas observadas, com contagens e janela de observação quando disponíveis',
            '07-alagamento': 'potencial de alagamento, sem afirmar alagamento confirmado e sem usar inundação como nome do produto',
        }[scene_id]
        return (
            'Use até 5 frases curtas e no máximo 100 palavras, incluindo as frases obrigatórias. '
            'Organize os destaques confirmados por Sul, Sudeste, Nordeste, Centro-Oeste e Norte, '
            'priorizando a maior atenção sustentada pelo mesmo produto e período. '
            f'Nesta cena fale somente de {product}. '
            'Cite estados e localidades com localização confirmada; não invente destaques '
            'para preencher regiões sem dados nem interprete ausência de dados como ausência de risco. '
            'No mapa de raios, não descreva polígonos de severidade nem alagamento; '
            'cada produto tem sua própria cena. '
            'Só diga que os raios foram previstos se houver evidência explícita de previsão '
            'emitida antes dos eventos, cobrindo os mesmos locais e toda a janela observada, '
            'com resultado de comparação confirmado. Coincidência com um mapa atual ou '
            'risco muito baixo não prova acerto ou ausência de previsão. '
            'Sem essa comprovação, apresente apenas as observações, sem alegar acerto, '
            'falha ou que os raios não foram previstos. Não declare uma taxa de acerto '
            'com base somente nos casos favoráveis.'
        )
    if scene_id not in ('01-chuva', '02-ecens'):
        return ('Use 2 frases e no máximo 45 palavras, exceto frases obrigatórias. '
                'Ao destacar o Brasil, identifique a região e os estados ou localidades '
                'confirmados nos dados. Priorize a maior atenção sustentada pelo produto '
                'exibido; não repita o panorama das cinco regiões em cada cena.')
    product = ('chuva prevista, com acumulados somente quando confirmados'
               if scene_id == '01-chuva' else
               'Previsão de Raios, com a métrica da camada selecionada; não fale de chuva')
    return (
        'Use de 5 a 7 frases curtas e no máximo 120 palavras, incluindo a abertura. '
        f'Neste panorama de {product}, ao entrar no Brasil, cubra as cinco regiões: '
        + ', '.join(BRAZIL_REGIONS) + '. '
        'Priorize o Brasil desde a abertura; a América do Sul é apenas contexto breve. '
        'Comece pela região de maior atenção quando os dados permitirem comparar '
        'o mesmo produto e período; caso contrário use a ordem Sul, Sudeste, Nordeste, '
        'Centro-Oeste e Norte, sem inventar um ranking. Dê mais espaço aos destaques '
        'confirmados e uma passagem breve às demais, agrupando-as quando apropriado. '
        'Cite estados ou localidades apenas com evidência e localização regional '
        'confirmadas. Uma lista dos maiores valores não prova ausência de risco '
        'nas regiões omitidas. Se faltar cobertura, agrupe os nomes das regiões '
        'sem dados e informe a limitação uma única vez; não diga tempo tranquilo, '
        'sem chuva ou sem risco por ausência de dados. Não transforme potencial '
        'em ocorrência confirmada. Mantenha a fala no produto e no período do mapa '
        'exibido; não peça zoom regional enquanto a imagem permanecer continental.'
    )


def validate_scene_evidence(scene):
    """Reject missing local focus and unsupported monitoring conclusions."""
    import re
    import unicodedata
    def folded(value):
        return ''.join(c for c in unicodedata.normalize('NFD', value.casefold())
                       if unicodedata.category(c) != 'Mn')
    text = folded(scene.narration)
    if scene.available and scene.place and scene.category == 'destaque':
        city = folded(scene.place.get('nome', '').split(',')[0].strip())
        if city and city not in text:
            raise ValueError('a narração omitiu a cidade do destaque local')
        if city and 'destaque' not in text:
            raise ValueError('identifique o local como lugar de destaque')
    if scene.available and scene.view == 'chuva-prevista':
        # A top-city list is not an exhaustive regional rainfall analysis.
        for sentence in re.split(r'[.!?;]', text):
            rain = re.search(r'chuva|precipita|acumulad|pluviom', sentence)
            denial = re.search(r'nao (?:ha|hav[a-z]*|existe[a-z]*|tem|tera|deve[a-z]*|esta prevista|estao previstas|se preve|apresenta[a-z]*)|sem (?:previsao de |registro de )?(?:chuva|precipita)|nenhum[a]? (?:chuva|precipita)', sentence)
            if rain and denial:
                raise ValueError('ausência de chuva não comprovada por análise regional completa')
    if scene.id in ('05-agora', '07-alagamento'):
        # A rendered viewport, including an empty one, never certifies absence
        # throughout a macroregion. Prefer a scoped limitation to a false negative.
        negatives = (r'nao (?:ha|existe|existem|tem|foram identificad[oa]s?|foi identificad[oa]|'
                     r'foram detectad[oa]s?|foi detectad[oa]|apresenta|apresentam)'
                     r'[^.!?]{0,100}(?:sever|tempest|risco|alagamento)|'
                     r'sem (?:qualquer )?(?:severidade|tempestades?|risco(?:s)?(?: de alagamento)?)|'
                     r'nenhum[a]?[^.!?]{0,50}(?:sever|tempest|alagamento)')
        if re.search(negatives, text):
            raise ValueError('ausência de severidade ou risco não comprovada pela captura')
        if re.search(r'foram previstos|ja (?:estavam|haviam sido) previst|previsao acertou', text):
            raise ValueError('acerto de previsão sem verificação temporal estruturada')

    if scene.available:
        from .bulletin_context import brazilian_highlights
        highlights = brazilian_highlights(scene)
        if highlights and not any(folded(name) in text for name in highlights):
            raise ValueError('a fala omitiu todos os destaques brasileiros fornecidos')
