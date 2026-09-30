import os,re,subprocess,tempfile,threading,requests
from pathlib import Path
from flask import Flask,request,jsonify
from PIL import Image,ImageDraw,ImageFont
import imageio_ffmpeg
app=Flask(__name__); FFMPEG=imageio_ffmpeg.get_ffmpeg_exe()
def run(c): return subprocess.run(c,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
def ok(): return bool(os.environ.get('WORKER_SECRET')) and request.headers.get('Authorization')=='Bearer '+os.environ['WORKER_SECRET']
def cb(d,p):
 r=requests.post(d['callback_url'],headers={'Authorization':'Bearer '+d['callback_token'],'Content-Type':'application/json'},json=p,timeout=180); r.raise_for_status(); return r.json()
def put(url,headers,path):
 with open(path,'rb') as f:r=requests.put(url,headers=headers or {},data=f,timeout=900)
 r.raise_for_status()
def download(url,path):
 with requests.get(url,stream=True,timeout=900) as r:
  r.raise_for_status()
  with open(path,'wb') as f:
   for c in r.iter_content(1024*1024):
    if c:f.write(c)
def dims(path):
 p=run([FFMPEG,'-hide_banner','-i',path]); m=re.search(r'(\d{2,5})x(\d{2,5})',p.stderr)
 if not m: raise RuntimeError('Video boyutu okunamadı')
 return int(m.group(1)),int(m.group(2))
def getfont(sz):
 for p in ['/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf','/usr/share/fonts/truetype/liberation2/LiberationSans-Bold.ttf']:
  if Path(p).exists(): return ImageFont.truetype(p,sz)
 return ImageFont.load_default()
def wrap(dr,text,ft,mw):
 words=str(text).split(); lines=[]; line=''
 for w in words:
  t=(line+' '+w).strip(); b=dr.textbbox((0,0),t,font=ft,stroke_width=2)
  if line and b[2]-b[0]>mw: lines.append(line); line=w
  else: line=t
 if line: lines.append(line)
 if len(lines)>2: lines=[lines[0],' '.join(lines[1:])]
 return lines[:2]
def extract(d):
 tmp=tempfile.mkdtemp(prefix='ss-')
 try:
  src=f'{tmp}/source.mp4'; audio=f'{tmp}/audio.mp3'; download(d['source_url'],src)
  p=run([FFMPEG,'-y','-i',src,'-vn','-ac','1','-ar','16000','-b:a','64k',audio])
  if p.returncode: raise RuntimeError(p.stderr[-1200:])
  t=cb(d,{'stage':'audio_request','contentId':d['contentId'],'contentTitle':d.get('contentTitle'),'sourceAssetId':d['sourceAssetId'],'sizeBytes':os.path.getsize(audio)})
  put(t['upload_url'],t.get('upload_headers'),audio)
  cb(d,{'stage':'audio_ready','contentId':d['contentId'],'contentTitle':d.get('contentTitle'),'sourceAssetId':d['sourceAssetId'],'audioAssetId':t['assetId']})
 except Exception as e:
  try: cb(d,{'stage':'failed','contentId':d.get('contentId'),'message':str(e)[:1000]})
  except: pass
def render_job(d):
 tmp=tempfile.mkdtemp(prefix='ssr-')
 try:
  src=f'{tmp}/source.mp4'; out=f'{tmp}/TR-final.mp4'; download(d['source_url'],src)
  w,h=dims(src); ft=getfont(max(30,round(w*.047))); inputs=[]; filters=[]
  for i,c in enumerate(d['cues']):
   im=Image.new('RGBA',(w,h),(0,0,0,0)); dr=ImageDraw.Draw(im); lines=wrap(dr,c['text'],ft,int(w*.84)); lh=max(42,round(w*.058)); y=int(h*.79-(len(lines)-1)*lh/2)
   for j,line in enumerate(lines):
    sw=max(3,round(w*.004)); b=dr.textbbox((0,0),line,font=ft,stroke_width=sw); tw=b[2]-b[0]
    dr.text(((w-tw)/2,y+j*lh),line,font=ft,fill='white',stroke_width=sw,stroke_fill=(0,0,0,230))
   png=f'{tmp}/c{i}.png'; im.save(png); inputs+=['-i',png]
   prev='[0:v]' if i==0 else f'[v{i}]'; nxt=f'[v{i+1}]'; filters.append(f"{prev}[{i+1}:v]overlay=0:0:enable='between(t,{float(c['start']):.3f},{float(c['end']):.3f})'{nxt}")
  p=run([FFMPEG,'-y','-i',src]+inputs+['-filter_complex',';'.join(filters),'-map',f'[v{len(filters)}]','-map','0:a?','-c:v','libx264','-preset','veryfast','-crf','20','-c:a','aac','-b:a','192k','-movflags','+faststart','-shortest',out])
  if p.returncode: raise RuntimeError(p.stderr[-1600:])
  t=cb(d,{'stage':'render_request','contentId':d['contentId'],'contentTitle':d.get('contentTitle'),'sizeBytes':os.path.getsize(out)})
  put(t['upload_url'],t.get('upload_headers'),out); cb(d,{'stage':'final_ready','contentId':d['contentId'],'finalAssetId':t['assetId']})
 except Exception as e:
  try: cb(d,{'stage':'failed','contentId':d.get('contentId'),'message':str(e)[:1000]})
  except: pass
@app.get('/')
def index(): return jsonify(service='scrieneshots-video-worker',ok=True)
@app.get('/health')
def health():
 v=run([FFMPEG,'-version']); return jsonify(ok=v.returncode==0,ffmpeg=(v.stdout.splitlines() or ['missing'])[0])
@app.post('/process')
def process():
 if not ok(): return jsonify(error='unauthorized'),401
 d=request.get_json(force=True); threading.Thread(target=extract,args=(d,),daemon=True).start(); return jsonify(accepted=True,status='extracting'),202
@app.post('/render')
def render_endpoint():
 if not ok(): return jsonify(error='unauthorized'),401
 d=request.get_json(force=True); threading.Thread(target=render_job,args=(d,),daemon=True).start(); return jsonify(accepted=True,status='rendering'),202
