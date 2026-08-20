from __future__ import annotations

import base64, hashlib, hmac, json, os, secrets, time, uuid
from datetime import datetime, timezone
from functools import wraps
from pathlib import Path

import requests
from flask import Flask, jsonify, request, send_from_directory
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import desc, func
from werkzeug.utils import secure_filename

BASE=Path(__file__).resolve().parent
MEDIA_ROOT=Path(os.environ.get("PRIME_MEDIA_ROOT",BASE/"media")); MEDIA_ROOT.mkdir(parents=True,exist_ok=True)
app=Flask(__name__,static_folder=str(BASE)); app.config.update(SQLALCHEMY_DATABASE_URI=os.environ.get("DATABASE_URL","sqlite:///prime_dev.db"),SQLALCHEMY_TRACK_MODIFICATIONS=False,MAX_CONTENT_LENGTH=10*1024*1024,SESSION_COOKIE_HTTPONLY=True,SESSION_COOKIE_SAMESITE="Lax")
db=SQLAlchemy(app)
limiter=Limiter(key_func=get_remote_address,app=app,default_limits=["300 per hour"],storage_uri=os.environ.get("RATELIMIT_STORAGE_URI","memory://"))
JWT_SECRET=os.environ.get("PRIME_JWT_SECRET","").strip(); GEMINI_API_KEY=os.environ.get("GEMINI_API_KEY","").strip(); GEMINI_MODEL=os.environ.get("GEMINI_MODEL","gemini-2.5-flash")
MAX_AUDIO=25*1024*1024; ALLOWED_AUDIO={"mp3","wav","ogg","m4a","aac","flac","webm"}

class User(db.Model):
 id=db.Column(db.String(36),primary_key=True); email=db.Column(db.String(255),unique=True,nullable=True,index=True); password_hash=db.Column(db.String(255),nullable=True); name=db.Column(db.String(50),nullable=False,default="PRIME USER"); elo=db.Column(db.Integer,nullable=False,default=1000); prime_score=db.Column(db.Integer,nullable=False,default=50); wins=db.Column(db.Integer,nullable=False,default=0); losses=db.Column(db.Integer,nullable=False,default=0); games=db.Column(db.Integer,nullable=False,default=0); created_at=db.Column(db.DateTime(timezone=True),nullable=False,default=lambda:datetime.now(timezone.utc))
class FaceAnalysis(db.Model):
 id=db.Column(db.String(36),primary_key=True); user_id=db.Column(db.String(36),db.ForeignKey("user.id",ondelete="CASCADE"),nullable=False,index=True); score=db.Column(db.Integer,nullable=False); analysis_type=db.Column(db.String(20),nullable=False); summary=db.Column(db.Text,nullable=False,default=""); metrics_json=db.Column(db.Text,nullable=False,default="{}"); tips_json=db.Column(db.Text,nullable=False,default="[]"); confidence=db.Column(db.Integer,nullable=False,default=0); created_at=db.Column(db.DateTime(timezone=True),nullable=False,default=lambda:datetime.now(timezone.utc))
class EloMatch(db.Model):
 id=db.Column(db.String(36),primary_key=True); winner_id=db.Column(db.String(36),db.ForeignKey("user.id",ondelete="SET NULL")); loser_id=db.Column(db.String(36),db.ForeignKey("user.id",ondelete="SET NULL")); winner_elo_before=db.Column(db.Integer,nullable=False); loser_elo_before=db.Column(db.Integer,nullable=False); winner_delta=db.Column(db.Integer,nullable=False); loser_delta=db.Column(db.Integer,nullable=False); opponent_name=db.Column(db.String(50),nullable=False); is_bot=db.Column(db.Boolean,nullable=False,default=False); created_at=db.Column(db.DateTime(timezone=True),nullable=False,default=lambda:datetime.now(timezone.utc))
class MusicTrack(db.Model):
 id=db.Column(db.String(36),primary_key=True); user_id=db.Column(db.String(36),db.ForeignKey("user.id",ondelete="CASCADE"),nullable=False,index=True); original_name=db.Column(db.String(255),nullable=False); stored_name=db.Column(db.String(100),nullable=False,unique=True); mime_type=db.Column(db.String(100),nullable=False); size=db.Column(db.Integer,nullable=False); created_at=db.Column(db.DateTime(timezone=True),nullable=False,default=lambda:datetime.now(timezone.utc))

def password_hash(password):
 salt=secrets.token_bytes(16); digest=hashlib.scrypt(password.encode(),salt=salt,n=2**14,r=8,p=1); return f"scrypt${base64.urlsafe_b64encode(salt).decode()}${base64.urlsafe_b64encode(digest).decode()}"
def password_ok(password,encoded):
 try:
  _,s,d=encoded.split("$",2); salt=base64.urlsafe_b64decode(s.encode()); expected=base64.urlsafe_b64decode(d.encode()); return hmac.compare_digest(hashlib.scrypt(password.encode(),salt=salt,n=2**14,r=8,p=1),expected)
 except Exception:return False
def jwt_encode(user_id):
 if not JWT_SECRET: raise RuntimeError("PRIME_JWT_SECRET is not configured")
 h=base64.urlsafe_b64encode(b'{"alg":"HS256","typ":"JWT"}').rstrip(b"=").decode(); p=base64.urlsafe_b64encode(json.dumps({"sub":user_id,"exp":int(time.time())+604800},separators=(",",":")).encode()).rstrip(b"=").decode(); body=f"{h}.{p}"; s=base64.urlsafe_b64encode(hmac.new(JWT_SECRET.encode(),body.encode(),hashlib.sha256).digest()).rstrip(b"=").decode(); return f"{body}.{s}"
def current_user():
 auth=request.headers.get("Authorization","")
 if not auth.startswith("Bearer ") or not JWT_SECRET:return None
 try:
  h,p,s=auth[7:].split("."); body=f"{h}.{p}"; expected=base64.urlsafe_b64encode(hmac.new(JWT_SECRET.encode(),body.encode(),hashlib.sha256).digest()).rstrip(b"=").decode();
  if not hmac.compare_digest(s,expected):return None
  data=json.loads(base64.urlsafe_b64decode(p+"="*(-len(p)%4))); 
  if int(data["exp"])<int(time.time()):return None
  return db.session.get(User,data["sub"])
 except Exception:return None
def auth_required(fn):
 @wraps(fn)
 def wrapped(*args,**kwargs):
  user=current_user();
  if not user:return jsonify({"error":"authentication required"}),401
  return fn(user,*args,**kwargs)
 return wrapped
def user_json(u):return {"id":u.id,"email":u.email,"name":u.name,"elo":u.elo,"prime_score":u.prime_score,"wins":u.wins,"losses":u.losses,"games":u.games}

@app.get("/")
def index():return send_from_directory(BASE,"index.html")
@app.get("/<path:filename>")
def static_files(filename):return send_from_directory(BASE,filename)

@app.post("/api/auth/register")
@limiter.limit("5 per minute")
def register():
 data=request.get_json(force=True) or {}; email=str(data.get("email","")).strip().lower(); password=str(data.get("password","")); name=str(data.get("name","PRIME USER")).strip()[:50] or "PRIME USER"
 if len(password)<10 or "@" not in email:return jsonify({"error":"valid email and password of at least 10 characters required"}),400
 if User.query.filter_by(email=email).first():return jsonify({"error":"email already registered"}),409
 if not JWT_SECRET:return jsonify({"error":"authentication service is not configured"}),503
 user=User(id=str(uuid.uuid4()),email=email,password_hash=password_hash(password),name=name); db.session.add(user); db.session.commit(); return jsonify({"token":jwt_encode(user.id),"user":user_json(user)}),201
@app.post("/api/auth/login")
@limiter.limit("10 per minute")
def login():
 data=request.get_json(force=True) or {}; user=User.query.filter_by(email=str(data.get("email","")).strip().lower()).first()
 if not user or not user.password_hash or not password_ok(str(data.get("password","")),user.password_hash):return jsonify({"error":"invalid credentials"}),401
 if not JWT_SECRET:return jsonify({"error":"authentication service is not configured"}),503
 return jsonify({"token":jwt_encode(user.id),"user":user_json(user)})
@app.get("/api/me")
@auth_required
def me(user):return jsonify(user_json(user))
@app.put("/api/profile")
@auth_required
def update_profile(user):
 data=request.get_json(force=True) or {}; user.name=str(data["name"]).strip()[:50] or user.name if "name" in data else user.name; user.prime_score=max(0,min(100,int(data["prime_score"]))) if "prime_score" in data else user.prime_score; db.session.commit(); return jsonify(user_json(user))
@app.get("/api/profile")
@auth_required
def profile(user):return jsonify(user_json(user))
@app.get("/api/leaderboard")
def leaderboard():
 rows=User.query.order_by(desc(User.elo),desc(User.wins),desc(User.prime_score)).limit(100).all(); return jsonify([{**user_json(u),"rank":i+1} for i,u in enumerate(rows)])
@app.post("/api/elo/match")
@auth_required
def match(user):
 import random
 opponent=User.query.filter(User.id!=user.id).order_by(func.random()).first(); is_bot=opponent is None; opp_elo=random.randint(900,1150) if is_bot else opponent.elo; opp_name="PRIME BOT" if is_bot else opponent.name; win=user.prime_score+random.gauss(0,8)>=(random.randint(45,80) if is_bot else opponent.prime_score)+random.gauss(0,8); expected=1/(1+10**((opp_elo-user.elo)/400)); k=32; delta=max(8,round(k*((1 if win else 0)-expected))); delta=delta if win else -abs(delta); user_before=user.elo; user.elo=max(400,user.elo+delta); user.games+=1; user.wins+=int(win); user.losses+=int(not win); winner_id=user.id if win else (opponent.id if opponent else None); loser_id=opponent.id if win and opponent else (user.id if not win else None)
 if opponent:
  opp_delta=round(k*((0 if win else 1)-(1-expected))); opponent_before=opponent.elo; opponent.elo=max(400,opponent.elo+opp_delta); opponent.games+=1; opponent.wins+=int(not win); opponent.losses+=int(win)
 else:opponent_before=opp_elo; opp_delta=-delta
 db.session.add(EloMatch(id=str(uuid.uuid4()),winner_id=winner_id,loser_id=loser_id,winner_elo_before=user_before if win else opponent_before,loser_elo_before=opponent_before if win else user_before,winner_delta=delta if win else opp_delta,loser_delta=opp_delta if win else delta,opponent_name=opp_name,is_bot=is_bot)); db.session.commit(); return jsonify({"win":win,"delta":delta,"opponent":opp_name,"opponent_elo":opp_elo,"elo":user.elo,"is_bot":is_bot})
@app.get("/api/elo/history")
@auth_required
def elo_history(user):
 rows=EloMatch.query.filter((EloMatch.winner_id==user.id)|(EloMatch.loser_id==user.id)).order_by(desc(EloMatch.created_at)).limit(100).all(); return jsonify([{"id":x.id,"opponent":x.opponent_name,"is_bot":x.is_bot,"created_at":x.created_at.isoformat(),"delta":x.winner_delta if x.winner_id==user.id else x.loser_delta} for x in rows])

def extract_json(text):
 try:return json.loads(text.strip())
 except Exception:
  a,b=text.find("{"),text.rfind("}");
  if a<0 or b<a:raise ValueError("AI did not return JSON")
  return json.loads(text[a:b+1])
def gemini_json(prompt,image_b64=None,mime="image/jpeg"):
 if not GEMINI_API_KEY:raise RuntimeError("AI service is not configured")
 parts=[{"text":prompt}];
 if image_b64:parts.append({"inline_data":{"mime_type":mime,"data":image_b64}})
 payload={"contents":[{"parts":parts}],"generationConfig":{"temperature":0.2,"responseMimeType":"application/json"}}; url=f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent"; r=requests.post(url,params={"key":GEMINI_API_KEY},json=payload,timeout=45); r.raise_for_status(); return extract_json("".join(p.get("text","") for c in r.json().get("candidates",[]) for p in c.get("content",{}).get("parts",[])))
@app.post("/api/face-ai")
@auth_required
@limiter.limit("10 per minute")
def face_ai(user):
 data=request.get_json(force=True) or {}; image_b64=data.get("image");
 if not image_b64:return jsonify({"error":"image is required"}),400
 try:raw=base64.b64decode(image_b64,validate=True)
 except Exception:return jsonify({"error":"invalid image"}),400
 if len(raw)>8*1024*1024:return jsonify({"error":"image too large"}),413
 prompt='''You are the PRIME visual self-improvement coach. Analyze only visible, non-sensitive presentation features. Do not identify the person or infer age, race, ethnicity, religion, health, sexual orientation, or other sensitive traits. Do not diagnose or sexualize. Return ONLY JSON with score, type, summary, metrics (symmetry, proportion, grooming, hair, skin_appearance, presentation), tips and confidence. All numeric fields 0-100 integers. Tips must be practical and safe. If no clear face, confidence <=20.'''
 try:
  result=gemini_json(prompt,base64.b64encode(raw).decode("ascii"),data.get("mime","image/jpeg")); score=max(0,min(100,int(result.get("score",0)))); result["score"]=score; result["confidence"]=max(0,min(100,int(result.get("confidence",0)))); result["metrics"]={k:max(0,min(100,int(v))) for k,v in (result.get("metrics") or {}).items()}; result["tips"]=[str(x)[:300] for x in (result.get("tips") or [])[:5]]; a=FaceAnalysis(id=str(uuid.uuid4()),user_id=user.id,score=score,analysis_type=str(result.get("type","HTN"))[:20],summary=str(result.get("summary",""))[:2000],metrics_json=json.dumps(result["metrics"]),tips_json=json.dumps(result["tips"]),confidence=result["confidence"]); user.prime_score=score; db.session.add(a); db.session.commit(); return jsonify(result|{"analysis_id":a.id})
 except requests.RequestException:return jsonify({"error":"AI service temporarily unavailable"}),502
 except Exception:return jsonify({"error":"AI analysis failed"}),502
@app.get("/api/face/history")
@auth_required
def face_history(user):
 rows=FaceAnalysis.query.filter_by(user_id=user.id).order_by(desc(FaceAnalysis.created_at)).limit(100).all(); return jsonify([{"id":x.id,"score":x.score,"type":x.analysis_type,"summary":x.summary,"metrics":json.loads(x.metrics_json),"tips":json.loads(x.tips_json),"confidence":x.confidence,"created_at":x.created_at.isoformat()} for x in rows])
@app.post("/api/advice")
@auth_required
@limiter.limit("20 per minute")
def advice(user):
 try:return jsonify(gemini_json("Give 4 short, safe, practical self-improvement tips based only on this Prime Score. Never diagnose, sexualize, infer sensitive traits, recommend drugs, starvation, steroids or surgery. Score: "+str(user.prime_score)))
 except Exception:return jsonify({"tips":["Keep a stable sleep schedule.","Train consistently rather than chasing extreme routines.","Focus on grooming and clothing fit.","Use consistent lighting and angles for photo comparisons."]})
@app.get("/api/music")
@auth_required
def music_list(user):
 rows=MusicTrack.query.filter_by(user_id=user.id).order_by(desc(MusicTrack.created_at)).all(); return jsonify([{"id":x.id,"name":x.original_name,"mime":x.mime_type,"size":x.size,"created_at":x.created_at.isoformat(),"url":f"/api/music/{x.id}"} for x in rows])
@app.post("/api/music")
@auth_required
@limiter.limit("30 per hour")
def music_upload(user):
 file=request.files.get("file");
 if not file or not file.filename:return jsonify({"error":"file required"}),400
 ext=Path(secure_filename(file.filename)).suffix.lower().lstrip(".");
 if ext not in ALLOWED_AUDIO:return jsonify({"error":"unsupported audio format"}),415
 raw=file.read(MAX_AUDIO+1);
 if len(raw)>MAX_AUDIO:return jsonify({"error":"audio file too large"}),413
 track_id=str(uuid.uuid4()); stored=f"{track_id}.{ext}"; user_dir=MEDIA_ROOT/user.id; user_dir.mkdir(parents=True,exist_ok=True); (user_dir/stored).write_bytes(raw); track=MusicTrack(id=track_id,user_id=user.id,original_name=secure_filename(file.filename)[:255],stored_name=stored,mime_type=file.mimetype or "audio/mpeg",size=len(raw)); db.session.add(track); db.session.commit(); return jsonify({"id":track.id,"name":track.original_name,"url":f"/api/music/{track.id}"}),201
@app.get("/api/music/<track_id>")
@auth_required
def music_stream(user,track_id):
 track=MusicTrack.query.filter_by(id=track_id,user_id=user.id).first();
 if not track:return jsonify({"error":"track not found"}),404
 path=MEDIA_ROOT/user.id/track.stored_name
 if not path.is_file():return jsonify({"error":"file missing"}),404
 from flask import send_file
 return send_file(path,mimetype=track.mime_type,conditional=True,download_name=track.original_name)
@app.delete("/api/music/<track_id>")
@auth_required
def music_delete(user,track_id):
 track=MusicTrack.query.filter_by(id=track_id,user_id=user.id).first();
 if not track:return jsonify({"error":"track not found"}),404
 path=MEDIA_ROOT/user.id/track.stored_name
 if path.exists():path.unlink()
 db.session.delete(track); db.session.commit(); return jsonify({"ok":True})
@app.get("/health")
def health():db.session.execute(db.text("SELECT 1")); return jsonify({"status":"ok"})

with app.app_context():db.create_all()
if __name__=="__main__":app.run(host="127.0.0.1",port=int(os.environ.get("PORT","8765")),debug=False)
