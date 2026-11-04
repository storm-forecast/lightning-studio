"""Confirmed flood-zone keys for São Paulo municipal Shorts."""
import hashlib
import json

MAX_DAILY_SHORTS_PER_CITY = 1

def zone_key(area):
    """Stable key from a captured official polygon, never a guessed neighbourhood."""
    encoded=json.dumps(area['geometria'],sort_keys=True,separators=(',',':')).encode()
    return 'flood-' + hashlib.sha256(encoded).hexdigest()[:16]

def zones_for_city(areas, city_polygon):
    """Return only captured polygons intersecting the confirmed municipal boundary."""
    from shapely.geometry import shape
    municipality=shape(city_polygon)
    return [dict(area,zona_id=zone_key(area)) for area in areas if shape(area['geometria']).intersects(municipality)]

def confirmed_zones(source, city, state, areas):
    """Only zones intersecting the official municipal boundary are eligible."""
    boundary=source.municipal_boundary(city,state)
    if boundary.get('tipo') != 'limite_municipal':
        return []
    return zones_for_city(areas,boundary['geometria'])
