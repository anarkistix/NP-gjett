#!/usr/bin/env python3
import json
import re
import sys
from datetime import datetime
from pathlib import Path
import urllib.request, ssl
from typing import Dict, List, Tuple

try:
    from shapely.geometry import shape
    from shapely.ops import unary_union, transform as shp_transform
    from pyproj import Geod, Transformer
except Exception as e:
    print("Missing dependencies. Install with: pip install -r requirements.txt")
    raise

ROOT = Path(__file__).resolve().parent
DB_PATH = ROOT / 'np_database.json'
COUNTIES_PATH = ROOT / 'fylker2018.geojson'
MUNICIP_PATH = ROOT / 'kommuner2018.geojson'
HINTS_PATH = ROOT / 'park_hints.json'


def normalize_key(code: str, name: str) -> str:
    key = (code or name or '').lower()
    key = re.sub(r'[^a-z0-9æøå]', '', key)
    return key


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding='utf-8'))


def geod_area_km2(geom) -> float:
    geod = Geod(ellps='WGS84')
    # shapely >= 2.0 geometry_area_perimeter works on any polygon/multipolygon
    area_m2, _ = geod.geometry_area_perimeter(geom)
    return abs(area_m2) / 1_000_000.0


def get_name(props: Dict) -> str:
    for k in ('n', 'N', 'navn', 'NAVN', 'fylkesnavn', 'kommunenavn', 'KOMNAVN', 'name'):
        if k in props and props[k] is not None:
            return str(props[k])
    return ''


def extract_year_from_hints(hints_data: dict, code: str, name: str):
    parks = hints_data.get('parks') or {}
    # first try match by code
    key = None
    for k, v in parks.items():
        if str(v.get('code', '')).strip() == str(code or '').strip():
            key = k
            break
    if key is None:
        nrm = (name or '').strip().lower()
        key = nrm if nrm in parks else None
    entry = parks.get(key) if key else None
    hints = entry.get('hints') if entry else None
    if isinstance(hints, list):
        for h in hints:
            m = re.search(r'Opprettet i\s+(\d{4})', str(h), flags=re.IGNORECASE)
            if m:
                return int(m.group(1))
    return None


def main():
    if not DB_PATH.exists():
        print(f"Finner ikke {DB_PATH}")
        sys.exit(1)
    # Sørg for at fylkes/kommunegrenser finnes lokalt – forsøk GitHub-kilde hvis mangler
    ssl._create_default_https_context = ssl._create_unverified_context
    def ensure_file(path: Path, url: str):
        if path.exists() and path.stat().st_size > 1000:
            return
        try:
            data = urllib.request.urlopen(url, timeout=60).read()
            if data and len(data) > 1000:
                path.write_bytes(data)
                print(f"Lastet {path.name} fra {url}")
        except Exception as e:
            print(f"Kunne ikke hente {url}: {e}")

    if not COUNTIES_PATH.exists():
        ensure_file(COUNTIES_PATH, 'https://raw.githubusercontent.com/robhop/fylker-og-kommuner/main/Fylker-L.geojson')
    if not MUNICIP_PATH.exists():
        ensure_file(MUNICIP_PATH, 'https://raw.githubusercontent.com/robhop/fylker-og-kommuner/main/Kommuner-L.geojson')
    if not COUNTIES_PATH.exists() or not MUNICIP_PATH.exists():
        print("Mangler fylkes/kommune-geojson. Legg dem i prosjektroten først eller kjør på nytt.")
        sys.exit(2)

    db = load_json(DB_PATH)
    feats = (db.get('dataset') or {}).get('features') or []
    parks = [f for f in feats if (f.get('properties') or {}).get('source') == 'park' and (f.get('properties') or {}).get('status') != 'deleted']

    counties_fc = load_json(COUNTIES_PATH)
    municip_fc = load_json(MUNICIP_PATH)
    hints = load_json(HINTS_PATH) if HINTS_PATH.exists() else { 'parks': {} }

    # Bestem om fylke/kommune-data er i UTM 33 (EPSG:32633) og reprojiser til WGS84 ved behov
    def needs_utm33_to_wgs84(fc: dict) -> bool:
        try:
            crs_name = (((fc.get('crs') or {}).get('properties') or {}).get('name') or '').upper()
            if 'EPSG::32633' in crs_name or 'EPSG:32633' in crs_name:
                return True
        except Exception:
            pass
        # Heuristikk: sjekk første koordinat for typiske UTM-verdier
        try:
            for f in (fc.get('features') or [])[:3]:
                g = f.get('geometry') or {}
                coords = g.get('coordinates')
                if not coords:
                    continue
                # finn et punkt dypt nok (første [x,y])
                def first_xy(obj):
                    if isinstance(obj, (list, tuple)):
                        if len(obj) >= 2 and isinstance(obj[0], (int, float)) and isinstance(obj[1], (int, float)):
                            return obj[0], obj[1]
                        for item in obj:
                            res = first_xy(item)
                            if res is not None:
                                return res
                    return None
                xy = first_xy(coords)
                if xy:
                    x, y = xy
                    if abs(x) > 1000 or abs(y) > 1000:
                        return True
        except Exception:
            pass
        return False

    transformer = Transformer.from_crs('EPSG:32633', 'EPSG:4326', always_xy=True)
    def to_wgs84_if_needed(geom_obj, do_transform: bool):
        if not do_transform:
            return geom_obj
        try:
            return shp_transform(transformer.transform, geom_obj)
        except Exception:
            return geom_obj

    counties_need_tx = needs_utm33_to_wgs84(counties_fc)
    municip_need_tx = needs_utm33_to_wgs84(municip_fc)

    # For speed: konverter county/municip geometries på forhånd (til WGS84)
    county_geoms: List[Tuple[str, object]] = []
    for c in (counties_fc.get('features') or []):
        try:
            nm = get_name(c.get('properties') or {})
            g = shape(c.get('geometry'))
            g = to_wgs84_if_needed(g, counties_need_tx)
            county_geoms.append((nm, g))
        except Exception:
            pass

    municip_geoms: List[Tuple[str, object]] = []
    for m in (municip_fc.get('features') or []):
        try:
            nm = get_name(m.get('properties') or {})
            g = shape(m.get('geometry'))
            g = to_wgs84_if_needed(g, municip_need_tx)
            municip_geoms.append((nm, g))
        except Exception:
            pass

    # Group park features by logical park (code or name)
    groups: Dict[str, List[dict]] = {}
    for f in parks:
        p = f.get('properties') or {}
        key = normalize_key(str(p.get('code') or ''), str(p.get('name') or ''))
        groups.setdefault(key, []).append(f)

    updated = 0
    total = len(groups)

    for key, arr in groups.items():
        # Merge geometry
        shps = []
        rep = arr[0].get('properties') or {}
        for f in arr:
            g = f.get('geometry')
            if not g: 
                continue
            try:
                shps.append(shape(g))
            except Exception:
                continue
        if not shps:
            continue
        merged = unary_union(shps)
        # Compute area
        area_km2 = round(geod_area_km2(merged), 1)
        # Intersections
        counties = sorted({ n for (n, cg) in county_geoms if n and merged.intersects(cg) })
        municips = sorted({ n for (n, mg) in municip_geoms if n and merged.intersects(mg) })
        # Established year
        year = extract_year_from_hints(hints, rep.get('code'), rep.get('name'))

        # Write back to each member feature (append-only semantics)
        for f in arr:
            p = f.setdefault('properties', {})
            changed = False
            if not p.get('areaKm2'):
                p['areaKm2'] = area_km2
                changed = True
            if not (isinstance(p.get('counties'), list) and p['counties']):
                p['counties'] = counties
                changed = True
            if not (isinstance(p.get('municipalities'), list) and p['municipalities']):
                p['municipalities'] = municips
                changed = True
            if year and not p.get('establishedYear'):
                p['establishedYear'] = year
                changed = True
            if changed:
                updated += 1

    # Write out if anything updated
    if updated:
        backup = DB_PATH.with_suffix('.enriched_' + datetime.now().strftime('%Y%m%d_%H%M%S') + '.json')
        backup.write_text(json.dumps(db, ensure_ascii=False, indent=2), encoding='utf-8')
        DB_PATH.write_text(json.dumps(db, ensure_ascii=False, indent=2), encoding='utf-8')
        print(f"Oppdatert {updated} park-features. Lagret og sikkerhetskopiert til {backup.name}")
    else:
        print("Ingen endringer. Alle park-features hadde allerede metadata.")


if __name__ == '__main__':
    main()


