"""Spanish for configured South American cities; Brazilian alerts retain Portuguese."""
DIRECTIONS={'norte':'norte','nordeste':'noreste','leste':'este','sudeste':'sureste','sul':'sur','sudoeste':'suroeste','oeste':'oeste','noroeste':'noroeste'}

def localize_report(report, observed_test=False):
    from .shorts_locales import SPANISH_CITIES
    key=report.get('cidade','cordoba')
    country,tz=SPANISH_CITIES[key]
    report.update(idioma='es-AR' if country=='Argentina' else 'es',voz='es-AR-ElenaNeural',timezone=tz,pais=country)
    advice=['Busque refugio en un edificio o vehículo cerrado.',
            'Evite espacios abiertos, árboles aislados y actividades en el agua.',
            'No cruce calles inundadas. Siga los avisos del servicio meteorológico y Protección Civil de su país.']
    report['recomendacoes']=advice
    reasons=[]
    if observed_test:
        reasons.append('actividad eléctrica observada en la región')
    else:
        if any('elétrica' in x for x in report['motivos']):reasons.append('tormenta con actividad eléctrica acercándose a la región')
        if report.get('aproximacao_chuva'):reasons.append('ecos de lluvia fuerte acercándose en el radar')
    report['motivos']=reasons
    text=f"Atención, {report.get('nome','Córdoba')}, {country}. Monitoreo de la zona hasta 40 kilómetros del centro. "
    text+=('; '.join(reasons)+'. ') if reasons else 'Sin señal confirmada de aproximación. '
    near=report['raios'].get('mais_proximo')
    if near and not report['raios']['dados_atrasados']:
        km=str(near['km']).replace('.',',')
        text+=f"Descarga más cercana a {km} kilómetros, hacia el {DIRECTIONS.get(near['direcao'],near['direcao'])}. "
    trend=(report['raios'].get('tendencia') or {}).get('sentido')
    if trend=='afastando':text+='La tendencia de la actividad eléctrica indica alejamiento, no aproximación. '
    point=report.get('nowcasting') or {};motion=point.get('deslocamento')
    if motion:text+=f"Movimiento estimado de las células hacia el {DIRECTIONS.get(motion['para'],motion['para'])}, a {motion['velocidade_kmh']} kilómetros por hora. "
    text+='El riesgo es regional y no confirma impacto en todos los barrios. '+' '.join(advice)
    report['roteiro']=text


def screen_es(value):
    mapping={
      'ALERTA • NOWCASTING':'ALERTA • NOWCASTING',
      'Raios observados':'Descargas observadas',
      'Risco de tempestade (estimativa)':'Riesgo de tormenta (estimado)',
      'Recomendações finais':'Recomendaciones finales',
      'PROTEJA-SE':'PROTÉJASE', 'PREVISÃO LOCAL':'PRONÓSTICO LOCAL',
      'N ↑ • Amarelo: raios • Centro marcado':'N ↑ • Amarillo: rayos • Centro señalado',
      'N ↑ • Risco: baixo / moderado / alto':'N ↑ • Riesgo: bajo / moderado / alto',
      'APRESENTADORA IA':'PRESENTADORA IA',
      'Estimativa regional • acompanhe a Defesa Civil':'Estimación regional • siga a Defensa Civil'}
    if value in mapping:return mapping[value]
    for key, translated in mapping.items():
        if value == key.upper():return translated.upper()
    for a,b in [('Risco agora: ','Riesgo actual: '),('Movimento não determinado','Movimiento no determinado'),('Movimento: ','Movimiento: '),('indisponível','no disponible'),(' raios / ',' rayos / '),('alta','alto'),('moderada','moderado'),('baixa','bajo'),('baixo','bajo')]:value=value.replace(a,b)
    for a,b in DIRECTIONS.items():
        if value.startswith('Movimiento: '+a+' •'):value=value.replace('Movimiento: '+a+' •','Movimiento: '+b+' •')
    return value
