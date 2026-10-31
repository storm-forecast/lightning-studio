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


def flood_copy(scene):
    names = flood_places(scene)
    if not names:
        return ''
    product = 'severidade no monitoramento' if scene.id == '05-agora' else 'potencial de alagamento'
    caveat = ('que já ocorreu alagamento' if scene.id == '07-alagamento' else 'danos confirmados')
    return ('As áreas destacadas para análise de ' + product + ' ficam na região de ' +
            '; '.join(names) + '. Essas localidades são referências geográficas próximas às áreas '
            'do mapa; não significa que todo o município será afetado nem confirma ' + caveat + '. '
            'Não atravesse vias alagadas e acompanhe os avisos da Defesa Civil.')
