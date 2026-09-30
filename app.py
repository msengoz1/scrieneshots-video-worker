import os, subprocess
from flask import Flask, request, jsonify
app=Flask(__name__)
def run(cmd): return subprocess.run(cmd,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
@app.get("/")
def index(): return jsonify(service="scrieneshots-video-worker",ok=True)
@app.get("/health")
def health():
    v=run(["ffmpeg","-version"]); f=run(["ffmpeg","-hide_banner","-filters"])
    return jsonify(ok=v.returncode==0,ffmpeg=(v.stdout.splitlines() or ["missing"])[0],subtitles_filter=(" subtitles " in f.stdout))
@app.post("/process")
def process_video():
    secret=os.environ.get("WORKER_SECRET","")
    if not secret or request.headers.get("Authorization") != f"Bearer {secret}": return jsonify(error="unauthorized"),401
    d=request.get_json(force=True,silent=True) or {}
    if not d.get("source_url") or not d.get("upload_url"): return jsonify(error="source_url and upload_url are required"),400
    return jsonify(accepted=True,status="worker_ready"),202
