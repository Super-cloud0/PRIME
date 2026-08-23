from flask import Flask, jsonify, request, send_from_directory, Response
import sqlite3, os, random, time, base64, json, urllib.request, urllib.error

BASE = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(BASE, "prime.db")
app = Flask(__name__, static_folder=BASE)
MAX_MUSIC_BYTES = 15 * 1024 * 1024

def db():
    c = sqlite3.connect(DB)
    c.row_factory = sqlite3.Row
    c.execute("""CREATE TABLE IF NOT EXISTS users(
        id TEXT PRIMARY KEY, name TEXT NOT NULL, elo INTEGER NOT NULL DEFAULT 1000,
        prime_score INTEGER NOT NULL DEFAULT 50, wins INTEGER NOT NULL DEFAULT 0,
        losses INTEGER NOT NULL DEFAULT 0, games INTEGER NOT NULL DEFAULT 0,
        created_at REAL NOT NULL)""")
    c.execute("""CREATE TABLE IF NOT EXISTS music(
        id INTEGER PRIMARY KEY AUTOINCREMENT, user_id TEXT NOT NULL, name TEXT NOT NULL,
        mime TEXT NOT NULL DEFAULT 'audio/mpeg', data BLOB NOT NULL, created_at REAL NOT NULL,
        FOREIGN KEY(user_id) REFERENCES users(id))""")
    c.commit()
    return c

def ensure_user(c, uid, name="PRIME USER"):
    c.execute("INSERT OR IGNORE INTO users(id,name,created_at) VALUES(?,?,?)",
              (uid, (name or "PRIME USER")[:50], time.time()))

@app.get("/")
def index(): return send_from_directory(BASE, "index.html")

@app.get("/<path:filename>")
def static_files(filename): return send_from_directory(BASE, filename)

@app.get("/api/profile")
def profile():
    uid = request.args.get("id"); name = request.args.get("name") or "PRIME USER"
    if not uid: return jsonify({"error":"id required"}), 400
    c = db(); ensure_user(c, uid, name); c.commit()
    row = c.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone(); c.close()
    return jsonify(dict(row))

@app.post("/api/profile")
def update_profile():
    data = request.get_json(force=True) or {}; uid = data.get("id")
    name = (data.get("name") or "PRIME USER")[:50]
    if not uid: return jsonify({"error":"id required"}), 400
    c = db(); ensure_user(c, uid, name); fields=[]; values=[]
    if "name" in data: fields.append("name=?"); values.append(name)
    if "prime_score" in data:
        try: score = int(max(0, min(100, int(data.get("prime_score")))))
        except (TypeError, ValueError): c.close(); return jsonify({"error":"prime_score must be a number"}), 400
        fields.append("prime_score=?"); values.append(score)
    if fields:
        values.append(uid); c.execute(f"UPDATE users SET {', '.join(fields)} WHERE id=?", values); c.commit()
    row=c.execute("SELECT * FROM users WHERE id=?",(uid,)).fetchone(); c.close(); return jsonify(dict(row))

@app.get("/api/leaderboard")
def leaderboard():
    c=db(); rows=c.execute("SELECT id,name,elo,prime_score,wins,losses,games FROM users ORDER BY elo DESC,wins DESC,prime_score DESC LIMIT 100").fetchall(); c.close()
    return jsonify([dict(r) for r in rows])

@app.post("/api/elo/match")
def match():
    data=request.get_json(force=True) or {}; uid=data.get("id")
    if not uid: return jsonify({"error":"id required"}),400
    c=db(); me=c.execute("SELECT * FROM users WHERE id=?",(uid,)).fetchone()
    if not me: c.close(); return jsonify({"error":"profile not found"}),404
    opp=c.execute("SELECT * FROM users WHERE id<>? ORDER BY RANDOM() LIMIT 1",(uid,)).fetchone(); is_bot=opp is None
    if is_bot: opp_elo=random.randint(900,1150); opp_name="PRIME BOT"; opp_id=None
    else: opp_elo=opp["elo"]; opp_name=opp["name"]; opp_id=opp["id"]
    my_power=me["prime_score"]+random.gauss(0,8); opp_power=(opp["prime_score"] if not is_bot else random.randint(45,80))+random.gauss(0,8)
    win=my_power>=opp_power; expected=1/(1+10**((opp_elo-me["elo"])/400)); k=32
    delta=max(8,round(k*((1 if win else 0)-expected))); new_elo=max(400,me["elo"]+delta)
    c.execute("UPDATE users SET elo=?,games=games+1,wins=wins+?,losses=losses+? WHERE id=?",(new_elo,1 if win else 0,0 if win else 1,uid))
    if opp_id:
        opp_expected=1-expected; opp_delta=round(k*((0 if win else 1)-opp_expected))
        c.execute("UPDATE users SET elo=?,games=games+1,wins=wins+?,losses=losses+? WHERE id=?",(max(400,opp["elo"]+opp_delta),0 if win else 1,1 if win else 0,opp_id))
    c.commit(); c.close()
    return jsonify({"win":win,"delta":delta if win else -abs(delta),"opponent":opp_name,"opponent_elo":opp_elo,"elo":new_elo,"is_bot":is_bot})

# Per-user music: each PRIME account has its own playlist.
# MVP stores audio bytes in SQLite. Later move blobs to persistent/object storage.
@app.get("/api/music")
def music_list():
    uid=request.args.get("user_id")
    if not uid: return jsonify({"error":"user_id required"}),400
    c=db(); rows=c.execute("SELECT id,name,mime,created_at FROM music WHERE user_id=? ORDER BY id DESC",(uid,)).fetchall(); c.close()
    return jsonify([dict(r) for r in rows])

@app.post("/api/music")
def music_upload():
    data=request.get_json(force=True) or {}; uid=data.get("user_id"); name=(data.get("name") or "track")[:200]; mime=(data.get("mime") or "audio/mpeg")[:100]; encoded=data.get("data")
    if not uid or not encoded: return jsonify({"error":"user_id and data are required"}),400
    if not mime.startswith("audio/"): return jsonify({"error":"only audio files are allowed"}),400
    try: raw=base64.b64decode(encoded,validate=True)
    except Exception: return jsonify({"error":"invalid base64 audio"}),400
    if not raw: return jsonify({"error":"empty audio"}),400
    if len(raw)>MAX_MUSIC_BYTES: return jsonify({"error":"audio too large (max 15 MB per track)"}),413
    c=db(); ensure_user(c,uid); cur=c.execute("INSERT INTO music(user_id,name,mime,data,created_at) VALUES(?,?,?,?,?)",(uid,name,mime,sqlite3.Binary(raw),time.time())); c.commit(); track_id=cur.lastrowid; c.close()
    return jsonify({"id":track_id,"name":name,"mime":mime}),201

@app.get("/api/music/<int:track_id>")
def music_file(track_id):
    uid=request.args.get("user_id")
    if not uid: return jsonify({"error":"user_id required"}),400
    c=db(); row=c.execute("SELECT name,mime,data FROM music WHERE id=? AND user_id=?",(track_id,uid)).fetchone(); c.close()
    if not row: return jsonify({"error":"track not found"}),404
    safe_name=row["name"].replace('"','')
    return Response(row["data"],mimetype=row["mime"],headers={"Content-Disposition":f'inline; filename="{safe_name}"',"Cache-Control":"private, max-age=3600"})

@app.delete("/api/music/<int:track_id>")
def music_delete(track_id):
    data=request.get_json(silent=True) or {}; uid=data.get("user_id") or request.args.get("user_id")
    if not uid: return jsonify({"error":"user_id required"}),400
    c=db(); cur=c.execute("DELETE FROM music WHERE id=? AND user_id=?",(track_id,uid)); c.commit(); c.close()
    if cur.rowcount==0: return jsonify({"error":"track not found"}),404
    return jsonify({"ok":True})

# Gemini vision endpoint. API key stays server-side.
GEMINI_API_KEY=os.environ.get("GEMINI_API_KEY","").strip()
GEMINI_MODEL=os.environ.get("GEMINI_MODEL","gemini-2.5-flash")

def _extract_json(text):
    text=(text or "").strip()
    try: return json.loads(text)
    except Exception: pass
    m=__import__("re").search(r"\{.*\}",text,__import__("re").S)
    if not m: raise ValueError("Gemini did not return JSON")
    return json.loads(m.group(0))

@app.post("/api/face-ai")
def face_ai():
    if not GEMINI_API_KEY: return jsonify({"error":"GEMINI_API_KEY is not configured","hint":"Set GEMINI_API_KEY in Render Environment."}),503
    data=request.get_json(force=True) or {}; image_b64=data.get("image"); mime=data.get("mime","image/jpeg")
    if not image_b64: return jsonify({"error":"image is required"}),400
    try: raw=base64.b64decode(image_b64,validate=True)
    except Exception: return jsonify({"error":"invalid base64 image"}),400
    if len(raw)>8*1024*1024: return jsonify({"error":"image too large (max 8 MB)"}),413
    prompt="""
You are the PRIME visual self-improvement coach.
Analyze ONLY visible, non-sensitive presentation features in the supplied selfie.
Do NOT identify the person or infer age, race, ethnicity, religion, disability, health,
sexual orientation, or any other sensitive trait. Do NOT diagnose medical/skin conditions
and do not sexualize the person.
This is a presentation score for product feedback, not an objective measure of a person's
worth or attractiveness. Judge only what is clearly visible in this photo: lighting,
camera angle, expression, grooming, hairstyle, visible skin appearance, clothing/presentation,
facial balance and photographic composition. If a feature cannot be judged reliably, use a
neutral middle value instead of guessing. Avoid extreme scores unless the photo gives strong evidence.
Return ONLY valid JSON with this exact shape:
{"score":0,"type":"SUB 5 | MTN | HTN | LTN | CHAD","summary":"short neutral summary","metrics":{"symmetry":0,"proportion":0,"grooming":0,"hair":0,"skin_appearance":0,"presentation":0},"tips":["tip 1","tip 2","tip 3","tip 4"],"confidence":0}
Rules: every numeric field is 0-100; score stays reasonably close to the metric average;
confidence describes photo/analysis quality only; tips must be practical and safe; never recommend
surgery, starvation, drugs, steroids or self-harm; if no clear face, confidence <=20 and say so.
"""
    payload={"contents":[{"parts":[{"text":prompt},{"inline_data":{"mime_type":mime,"data":base64.b64encode(raw).decode("ascii")}}]}],"generationConfig":{"temperature":0.2,"responseMimeType":"application/json"}}
    url=f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent"
    req=urllib.request.Request(url,data=json.dumps(payload).encode("utf-8"),headers={"Content-Type":"application/json","x-goog-api-key":GEMINI_API_KEY},method="POST")
    try:
        with urllib.request.urlopen(req,timeout=45) as response: result=json.loads(response.read().decode("utf-8"))
        text=""
        for cand in result.get("candidates",[]):
            for part in cand.get("content",{}).get("parts",[]):
                if "text" in part: text+=part["text"]
        return jsonify(_extract_json(text))
    except urllib.error.HTTPError as e:
        body=e.read().decode("utf-8",errors="ignore"); return jsonify({"error":f"Gemini HTTP {e.code}","model":GEMINI_MODEL,"details":body[:2500]}),502
    except Exception as e: return jsonify({"error":"Gemini request failed","details":str(e)}),502

if __name__=="__main__":
    db().close()
    port = int(os.environ.get("PORT", "8765"))
    host = os.environ.get("HOST", "0.0.0.0")
    app.run(host=host, port=port, debug=False)
