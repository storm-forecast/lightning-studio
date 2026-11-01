"""Local clocks for Spanish alerts; Brazilian cities retain their defaults."""
SPANISH_CITIES = {
 'cordoba': ('Argentina','America/Argentina/Cordoba'),
 'buenos-aires': ('Argentina','America/Argentina/Buenos_Aires'),
 'santa-cruz-de-la-sierra': ('Bolivia','America/La_Paz'),
 'santiago': ('Chile','America/Santiago'),
 'bogota': ('Colombia','America/Bogota'),
 'guayaquil': ('Ecuador','America/Guayaquil'),
 'asuncion': ('Paraguay','America/Asuncion'),
 'lima': ('Perú','America/Lima'),
 'montevideo': ('Uruguay','America/Montevideo'),
 'caracas': ('Venezuela','America/Caracas'),
}

def city_timezone(key, region):
    if key in SPANISH_CITIES:return SPANISH_CITIES[key][1]
    return {'AM':'America/Manaus','MS':'America/Campo_Grande'}.get(region,'America/Sao_Paulo')
