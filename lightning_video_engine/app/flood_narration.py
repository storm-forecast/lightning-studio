"""Ground flood-potential copy in confirmed geographic references."""

def flood_places(scene):
    rows = scene.evidence.get('flood_references', {}).get('areas', [])
    names = []
    for row in scene.evidence.get('flood_references', {}).get('locais_interesse', []):
        if row.get('dentro_poligono') is True and row.get('pais') == 'Brasil' and row.get('cidade'):
            name = row['cidade'] + (', ' + row['estado'] if row.get('estado') else '')
            if name not in names:
                names.append(name)
    for row in rows:
        if row.get('cidade_confirmada') is True and row.get('pais') == 'Brasil' and row.get('cidade'):
            name = row['cidade'] + (', ' + row['estado'] if row.get('estado') else '')
            if name not in names:
                names.append(name)
    return names[:3]


def flood_local_references(scene):
    labels=[]
    for row in scene.evidence.get('flood_references', {}).get('areas', []):
        local=row.get('referencia_local', {})
        if not (row.get('cidade_confirmada') and local.get('dentro_poligono') is True):
            continue
        name=local.get('bairro') or local.get('via')
        if name:
            label=name + ', ' + row['cidade']
            if label not in labels: labels.append(label)
    return labels[:3]


def flood_copy(scene):
    names = flood_places(scene)
    if not names:
        return ''
    local=flood_local_references(scene)
    product = 'severidade no monitoramento' if scene.id == '05-agora' else 'potencial de alagamento'
    caveat = ('que já ocorreu alagamento' if scene.id == '07-alagamento' else 'danos confirmados')
    precaution = ('À população dessas regiões: evite vias alagadas e acompanhe os avisos da Defesa Civil.'
                  if scene.id == '07-alagamento' else
                  'À população dessas regiões: redobre a atenção, procure abrigo seguro durante tempestades e acompanhe os avisos da Defesa Civil.')
    return ('As áreas destacadas para análise de ' + product + ' ficam na região de ' +
            '; '.join(names) + '. Essas localidades são referências geográficas próximas às áreas '
            'do mapa; não significa que todo o município será afetado nem confirma ' + caveat + '. '
            + ((' Referências locais dentro dos polígonos: ' + '; '.join(local) + '. ') if local else ' ')
            + precaution)
