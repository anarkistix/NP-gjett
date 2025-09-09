import http.server
import socketserver
import json
import re
import os
from pathlib import Path
from urllib.parse import urlparse, parse_qs

ROOT = Path(__file__).resolve().parent
DB_FILE = ROOT / 'np_database.json'
HINTS_FILE = ROOT / 'park_hints.json'
HIGHSCORES_FILE = ROOT / 'highscores.json'

def load_db():
    return json.loads(DB_FILE.read_text(encoding='utf-8'))

def save_db(obj):
    backup = DB_FILE.with_suffix('.json.bak')
    if not backup.exists():
        backup.write_text(DB_FILE.read_text(encoding='utf-8'), encoding='utf-8')
    DB_FILE.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding='utf-8')

def load_highscores():
    if not HIGHSCORES_FILE.exists():
        print(f"⚠️ HIGHSCORES FILE MISSING: {HIGHSCORES_FILE} - returning empty list with 10 EMPTY slots")
        # Returner 10 tomme plasser
        return [{"name": "<EMPTY>", "score": 0} for _ in range(10)]
    try:
        data = json.loads(HIGHSCORES_FILE.read_text(encoding='utf-8'))
        print(f"✅ Loaded {len(data) if isinstance(data, list) else 'unknown'} hi-scores from file")
        # Håndter både gammel format {"list": [...]} og ny format [...]
        if isinstance(data, dict) and 'list' in data:
            scores = data['list']
        else:
            scores = data
        
        # Sørg for at det alltid er 10 plasser
        while len(scores) < 10:
            scores.append({"name": "<EMPTY>", "score": 0})
        
        return scores
    except Exception as e:
        print(f"❌ Error reading highscores file: {e}")
        # Returner 10 tomme plasser ved feil
        return [{"name": "<EMPTY>", "score": 0} for _ in range(10)]

def save_highscores(scores):
    backup = HIGHSCORES_FILE.with_suffix('.json.bak')
    if not backup.exists() and HIGHSCORES_FILE.exists():
        backup.write_text(HIGHSCORES_FILE.read_text(encoding='utf-8'), encoding='utf-8')
    HIGHSCORES_FILE.write_text(json.dumps(scores, ensure_ascii=False, indent=2), encoding='utf-8')

def ensure_ids(db_obj):
    changed = False
    feats = db_obj.get('dataset', {}).get('features') or []
    # finn maks eksisterende id
    max_id = 0
    for f in feats:
        pr = f.get('properties') or {}
        try:
            i = int(pr.get('id'))
        except Exception:
            i = None
        if isinstance(i, int):
            if i > max_id:
                max_id = i
        else:
            pr['id'] = None
    # tildel nye id-er for de som mangler
    for f in feats:
        pr = f.get('properties') or {}
        try:
            i = int(pr.get('id'))
        except Exception:
            i = None
        if not isinstance(i, int):
            max_id += 1
            pr['id'] = max_id
            f['properties'] = pr
            changed = True
    return changed

class Handler(http.server.SimpleHTTPRequestHandler):
    def end_headers(self):
        # CORS
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET,POST,OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        super().end_headers()

    def do_OPTIONS(self):
        self.send_response(204)
        self.end_headers()

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path == '/db':
            try:
                obj = load_db()
                # sørg for at alle features har id
                if ensure_ids(obj):
                    save_db(obj)
            except Exception:
                self.send_response(500); self.end_headers(); self.wfile.write(b'{}'); return
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps(obj, ensure_ascii=False).encode('utf-8'))
            return
        if parsed.path == '/highscores':
            try:
                scores = load_highscores()
            except Exception:
                self.send_response(500); self.end_headers(); self.wfile.write(b'[]'); return
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps(scores, ensure_ascii=False).encode('utf-8'))
            return
        if parsed.path == '/hints':
            try:
                if not HINTS_FILE.exists():
                    hints = { 'parks': {} }
                else:
                    hints = json.loads(HINTS_FILE.read_text(encoding='utf-8'))
            except Exception:
                self.send_response(500); self.end_headers(); self.wfile.write(b'{}'); return
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps(hints, ensure_ascii=False).encode('utf-8'))
            return
        self.send_response(404)
        self.end_headers()
        self.wfile.write(b'Not found')

    def do_POST(self):
        parsed = urlparse(self.path)
        q = parse_qs(parsed.query or '')
        try:
            length = int(self.headers.get('content-length') or 0)
        except Exception:
            length = 0
        raw = self.rfile.read(length) if length > 0 else b''
        try:
            body = json.loads(raw.decode('utf-8')) if raw else {}
            # Sørg for at body er et dictionary
            if not isinstance(body, dict):
                print(f"Warning: body is not dict, got {type(body)}: {body}")
                body = {}
        except Exception as e:
            print(f"JSON parse error: {e}, raw: {raw}")
            self.send_response(400); self.end_headers(); self.wfile.write(b'Invalid JSON'); return

        # full save
        if parsed.path == '/save-db':
            if not isinstance(body, dict) or 'dataset' not in body:
                self.send_response(400); self.end_headers(); self.wfile.write(b'Invalid schema'); return
            try:
                save_db(body)
            except Exception:
                self.send_response(500); self.end_headers(); self.wfile.write(b'Write failed'); return
            self.send_response(200); self.send_header('Content-Type','application/json'); self.end_headers(); self.wfile.write(b'{"ok":true}')
            return

        # save hints
        if parsed.path == '/save-hints':
            # body: { name?, code?, key?, hints: [str] }
            if not isinstance(body, dict) or not isinstance(body.get('hints'), list):
                self.send_response(400); self.end_headers(); self.wfile.write(b'Invalid schema'); return
            try:
                if not HINTS_FILE.exists():
                    hints_obj = { 'parks': {} }
                else:
                    hints_obj = json.loads(HINTS_FILE.read_text(encoding='utf-8'))
                parks = hints_obj.get('parks') or {}

                def norm_key(s: str) -> str:
                    s = (s or '').lower()
                    # bevar nordiske bokstaver
                    return re.sub(r'[^a-z0-9\u00e6\u00f8\u00e5]', '', s)

                # finn eksisterende nøkkel vha code eller navn
                code = str(body.get('code') or '').strip()
                name = str(body.get('name') or '').strip()
                key = str(body.get('key') or '').strip()

                found_key = None
                if code:
                    for k, v in parks.items():
                        try:
                            if str(v.get('code') or '').strip() == code:
                                found_key = k; break
                        except Exception:
                            pass
                if found_key is None and name:
                    nrm = norm_key(name)
                    if nrm in parks:
                        found_key = nrm
                    else:
                        # sjekk entry.name normalisert
                        for k, v in parks.items():
                            vn = norm_key(str(v.get('name') or ''))
                            if vn and vn == nrm:
                                found_key = k; break
                if found_key is None and key:
                    found_key = key
                if found_key is None:
                    found_key = norm_key(name) or code or 'ukjent'

                # rens hintliste -> bare str, trim, uten tomme
                hints_list = []
                for h in body.get('hints'):
                    try:
                        s = str(h).strip()
                        if s:
                            hints_list.append(s)
                    except Exception:
                        pass
                entry = parks.get(found_key) or {}
                if name:
                    entry['name'] = name
                if code:
                    entry['code'] = code
                entry['hints'] = hints_list
                parks[found_key] = entry
                hints_obj['parks'] = parks

                # backup én gang
                bak = HINTS_FILE.with_suffix('.json.bak')
                if not bak.exists() and HINTS_FILE.exists():
                    bak.write_text(HINTS_FILE.read_text(encoding='utf-8'), encoding='utf-8')
                HINTS_FILE.write_text(json.dumps(hints_obj, ensure_ascii=False, indent=2), encoding='utf-8')
            except Exception:
                self.send_response(500); self.end_headers(); self.wfile.write(b'Write failed'); return
            self.send_response(200); self.send_header('Content-Type','application/json'); self.end_headers(); self.wfile.write(b'{"ok":true}')
            return

        # save highscore
        if parsed.path == '/highscores':
            if not isinstance(body, dict):
                print(f"Highscore body is not dict: {type(body)}: {body}")
                self.send_response(400); self.end_headers(); self.wfile.write(b'Invalid body format'); return
            name = str(body.get('name') or '').strip()
            score = body.get('score')
            print(f"Highscore data: name='{name}', score={score}, body={body}")
            if not name or not isinstance(score, (int, float)) or score < 0:
                self.send_response(400); self.end_headers(); self.wfile.write(b'Invalid name/score'); return
            try:
                scores = load_highscores()
                print(f"📊 Current hi-scores before adding: {len(scores)} entries")
                
                # Sjekk om navnet allerede eksisterer og erstatt hvis ny score er høyere
                existing_index = None
                for i, existing_score in enumerate(scores):
                    if existing_score.get('name', '').lower() == name.lower():
                        existing_index = i
                        break
                
                if existing_index is not None:
                    # Navnet eksisterer - erstatt kun hvis ny score er høyere
                    existing_score = scores[existing_index]['score']
                    if int(score) > existing_score:
                        scores[existing_index] = {"name": name, "score": int(score)}
                        print(f"🔄 Updated existing entry: {name} from {existing_score} to {score}")
                    else:
                        print(f"⚠️ Score {score} not higher than existing {existing_score} for {name}")
                        self.send_response(200); self.send_header('Content-Type','application/json'); self.end_headers(); self.wfile.write(b'{"ok":true,"message":"Score not higher than existing"}'); return
                else:
                    # Nytt navn - legg til
                    scores.append({"name": name, "score": int(score)})
                    print(f"➕ Added new entry: {name} with {score} points")
                
                # Sorter etter score (høyest først) og behold top 10
                scores.sort(key=lambda x: x['score'], reverse=True)
                scores = scores[:10]
                print(f"💾 Saving {len(scores)} hi-scores to file")
                save_highscores(scores)
                print(f"✅ Hi-score saved successfully: {name} with {score} points")
            except Exception as e:
                print(f"❌ Error saving hi-score: {e}")
                self.send_response(500); self.end_headers(); self.wfile.write(b'Write failed'); return
            self.send_response(200); self.send_header('Content-Type','application/json'); self.end_headers(); self.wfile.write(b'{"ok":true}')
            return

        # targeted ops: update, delete, move
        try:
            db = load_db()
            feats = db.get('dataset',{}).get('features') or []
        except Exception:
            self.send_response(500); self.end_headers(); self.wfile.write(b'Could not load DB'); return

        def parse_id(v):
            try:
                return int(v)
            except Exception:
                return None

        def find_index(fid):
            for i,f in enumerate(feats):
                pr = f.get('properties') or {}
                vid = pr.get('id')
                try:
                    ivid = int(vid)
                except Exception:
                    ivid = None
                if ivid == fid:
                    return i
            return -1

        if parsed.path == '/update':
            fid = parse_id(body.get('id') or (q.get('id',[None])[0]))
            props = body.get('props') or {}
            if fid is None:
                self.send_response(400); self.end_headers(); self.wfile.write(b'Missing id'); return
            idx = find_index(fid)
            if idx < 0:
                self.send_response(404); self.end_headers(); self.wfile.write(b'Not found'); return
            allowed = {'name','code','status','display','source'}
            feats[idx].setdefault('properties',{})
            for k,v in props.items():
                if k in allowed:
                    feats[idx]['properties'][k] = v
            try:
                save_db(db)
            except Exception:
                self.send_response(500); self.end_headers(); self.wfile.write(b'Write failed'); return
            self.send_response(200); self.end_headers(); self.wfile.write(b'{"ok":true}')
            return

        if parsed.path == '/delete':
            fid = parse_id(body.get('id') or (q.get('id',[None])[0]))
            if fid is None:
                self.send_response(400); self.end_headers(); self.wfile.write(b'Missing id'); return
            idx = find_index(fid)
            if idx < 0:
                self.send_response(404); self.end_headers(); self.wfile.write(b'Not found'); return
            del feats[idx]
            try:
                save_db(db)
            except Exception:
                self.send_response(500); self.end_headers(); self.wfile.write(b'Write failed'); return
            self.send_response(200); self.end_headers(); self.wfile.write(b'{"ok":true}')
            return

        if parsed.path == '/move':
            fid = parse_id(body.get('id') or (q.get('id',[None])[0]))
            to = body.get('to') or {}
            if fid is None or not to:
                self.send_response(400); self.end_headers(); self.wfile.write(b'Missing id/to'); return
            idx = find_index(fid)
            if idx < 0:
                self.send_response(404); self.end_headers(); self.wfile.write(b'Not found'); return
            feats[idx].setdefault('properties',{})
            if 'code' in to: feats[idx]['properties']['code'] = str(to['code'])
            if 'name' in to: feats[idx]['properties']['name'] = str(to['name'])
            try:
                save_db(db)
            except Exception:
                self.send_response(500); self.end_headers(); self.wfile.write(b'Write failed'); return
            self.send_response(200); self.end_headers(); self.wfile.write(b'{"ok":true}')
            return

        self.send_response(404)
        self.end_headers()
        self.wfile.write(b'Not found')

if __name__ == '__main__':
    host = os.environ.get('HOST', '0.0.0.0')
    try:
        port = int(os.environ.get('PORT', '8777'))
    except Exception:
        port = 8777
    with socketserver.TCPServer((host, port), Handler) as httpd:
        print(f"Serving admin endpoints on http://{host}:{port}")
        httpd.serve_forever()


