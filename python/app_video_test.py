"""
Giao diện web CỤC BỘ để kiểm tra mô hình trên video: thả video -> bấm "Kiểm tra" -> video được cắt khung,
chạy mô hình -> xem NHẬT KÝ chạy, chẩn đoán lỗi và kết quả (ảnh có khung, vùng cắt, báo cáo).

Chạy:  python python/app_video_test.py        rồi mở http://127.0.0.1:8765  (tự mở trình duyệt)
Chỉ nghe ở 127.0.0.1 (chỉ máy bạn truy cập được). Mỗi lần chạy lưu ở result/web_runs/<thời gian>/ (có run.log).
Bên trong gọi python/test_video_model.py, nên cần cùng thư viện (opencv, ultralytics hoặc onnxruntime).
"""
import json, mimetypes, os, re, shutil, subprocess, sys, threading, time, webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

ROOT = Path(__file__).resolve().parent.parent
RUNS = ROOT / "result" / "web_runs"; RUNS.mkdir(parents=True, exist_ok=True)
S = {"state": "idle", "run": None, "log": [], "result": None}; LK = threading.Lock()
PORT = 8765

ENV = r'''
import sys, platform
print("Python", sys.version.split()[0], "|", platform.platform())
try:
    import torch; print("PyTorch", torch.__version__, "| CUDA dùng được:", torch.cuda.is_available(), "|", torch.cuda.get_device_name(0) if torch.cuda.is_available() else "không có GPU")
except Exception as e: print("PyTorch: không dùng được:", type(e).__name__)
try:
    import ultralytics; print("ultralytics", ultralytics.__version__)
except Exception as e: print("ultralytics: chưa cài")
try:
    import onnxruntime as o; print("onnxruntime", o.__version__, o.get_available_providers())
except Exception as e: print("onnxruntime: chưa cài")
try:
    import cv2; print("OpenCV", cv2.__version__)
except Exception as e: print("OpenCV: chưa cài")
'''

def find_models():
    out = []
    for pat in ("result/train_container/*/weights/*.pt", "result/train_container/*/weights/*.onnx", "runs/**/weights/*.pt", "models/*.onnx"):
        out += [str(p.relative_to(ROOT)) for p in ROOT.glob(pat)]
    return sorted(p for p in set(out) if "cct_s_v2" not in p)

ANSI = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")

def push(f, s):
    s = ANSI.sub("", s)
    with LK: S["log"].append(s)
    f.write(s + "\n"); f.flush()

def worker(run, video, q):
    d = RUNS / run; envv = {**os.environ, "PYTHONUTF8": "1"}
    with open(d / "run.log", "w", encoding="utf-8") as f:
        t0 = time.time(); P = lambda s: push(f, s)
        try:
            P(f"[{time.strftime('%H:%M:%S')}] Nhận video: {video.name} ({video.stat().st_size / 1e6:.1f} MB)")
            P("--- Môi trường")
            env = subprocess.run([sys.executable, "-c", ENV], capture_output=True, text=True, encoding="utf-8", errors="replace", env=envv)
            for ln in (env.stdout + env.stderr).splitlines(): P("  " + ln)
            cmd = [sys.executable, "-u", str(ROOT / "python" / "test_video_model.py"), "--source", str(video), "--model", q.get("model", ""),
                   "--imgsz", q.get("imgsz", "960"), "--fps", q.get("fps", "3"), "--conf", q.get("conf", "0.25"), "--backend", q.get("backend", "ultralytics")]
            if q.get("track") == "1": cmd.append("--track")
            if q.get("backend") == "onnx": cmd += ["--names", "bien_so"]
            if q.get("read") == "1" and q.get("backend") != "onnx": cmd.append("--read")
            if q.get("cut") == "1": cmd.append("--save-cut")
            P("--- Lệnh chạy"); P("  " + " ".join(cmd)); P("--- Nhật ký chạy mô hình")
            shutil.rmtree(ROOT / "result" / "12_video_test", ignore_errors=True)
            p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace", cwd=ROOT, env=envv)
            for ln in p.stdout: P("  " + ln.rstrip())
            rc = p.wait(); P(f"--- Kết thúc: mã thoát {rc}, mất {time.time() - t0:.0f}s")
            res = {"run": run, "rc": rc, "log": f"/files/{run}/run.log"}
            out = ROOT / "result" / "12_video_test"
            if rc == 0 and out.exists():
                shutil.copytree(out, d / "out", dirs_exist_ok=True)
                rep = ROOT / "result" / "12_video_test.txt"
                res.update(report=rep.read_text(encoding="utf-8") if rep.exists() else "", sheet=f"/files/{run}/out/frames/_tong_hop.jpg",
                           video=f"/files/{run}/out/annotated.mp4", data=f"/files/{run}/out/results.json", crops=[f"/files/{run}/out/crops/{c.name}" for c in sorted((d / "out" / "crops").glob("*.jpg"))[:24]])
            with LK: S["result"] = res; S["state"] = "done" if rc == 0 else "error"
        except Exception as e:
            P(f"LỖI trong giao diện: {type(e).__name__}: {e}")
            with LK: S["state"] = "error"; S["result"] = {"run": run, "rc": -1, "log": f"/files/{run}/run.log"}

class H(BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def send(self, code, body, ctype="application/json; charset=utf-8"):
        b = body if isinstance(body, bytes) else body.encode("utf-8")
        self.send_response(code); self.send_header("Content-Type", ctype); self.send_header("Content-Length", str(len(b))); self.end_headers(); self.wfile.write(b)
    def do_GET(self):
        u = urlparse(self.path); q = parse_qs(u.query)
        if u.path == "/": return self.send(200, PAGE, "text/html; charset=utf-8")
        if u.path == "/api/models": return self.send(200, json.dumps(find_models()))
        if u.path == "/api/status":
            n = int(q.get("from", ["0"])[0])
            with LK: body = json.dumps({"state": S["state"], "lines": S["log"][n:], "n": len(S["log"]), "result": S["result"]})
            return self.send(200, body)
        if u.path == "/api/open":
            sub = {"cut": "frames_cut", "processed": "frames_processed"}.get(q.get("dir", [""])[0], "")
            p = (RUNS / q.get("run", [""])[0] / "out" / sub).resolve()
            if RUNS.resolve() not in p.parents or not p.exists(): return self.send(404, json.dumps({"error": "không thấy thư mục"}))
            try:
                if hasattr(os, "startfile"): os.startfile(str(p))
            except Exception: pass
            return self.send(200, json.dumps({"path": str(p)}))
        if u.path.startswith("/files/"):
            p = (RUNS / unquote(u.path[7:])).resolve()
            if RUNS.resolve() not in p.parents or not p.is_file(): return self.send(404, "không thấy file", "text/plain; charset=utf-8")
            return self.send(200, p.read_bytes(), mimetypes.guess_type(p.name)[0] or "application/octet-stream")
        self.send(404, "404", "text/plain")
    def do_POST(self):
        u = urlparse(self.path); q = {k: v[0] for k, v in parse_qs(u.query).items()}
        if u.path != "/api/run": return self.send(404, "404", "text/plain")
        with LK:
            if S["state"] == "running": return self.send(409, json.dumps({"error": "Đang chạy một lần kiểm tra khác"}))
            run = time.strftime("%Y%m%d_%H%M%S"); S.update(state="running", run=run, log=[], result=None)
        d = RUNS / run; d.mkdir(parents=True, exist_ok=True)
        video = d / ("upload" + (Path(q.get("filename", "v.mp4")).suffix.lower() or ".mp4")); left = int(self.headers.get("Content-Length", 0))
        with open(video, "wb") as f:
            while left > 0:
                c = self.rfile.read(min(1 << 20, left))
                if not c: break
                f.write(c); left -= len(c)
        threading.Thread(target=worker, args=(run, video, q), daemon=True).start()
        self.send(200, json.dumps({"run": run}))

PAGE = r'''<!doctype html><html lang="vi"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Kiểm tra mô hình trên video</title><style>
:root{--steel:#2e4a5a;--wash:#e8edf0;--paper:#fff;--ink:#16232c;--mute:#5d6e7a;--blue:#2457a6;--line:#cdd6dc;--bad:#c0392b;--warn:#b7791f}
*{box-sizing:border-box}body{margin:0;background:var(--wash);color:var(--ink);font:15px/1.5 Bahnschrift,"Segoe UI",system-ui,sans-serif}
header{background:repeating-linear-gradient(90deg,#2e4a5a 0 7px,#37576a 7px 14px);color:#fff;padding:18px 28px}
header h1{margin:0;font-size:22px;font-weight:600;letter-spacing:.2px}header p{margin:2px 0 0;opacity:.8;font-size:14px}
main{display:grid;grid-template-columns:340px 1fr;gap:20px;padding:20px 28px;max-width:1500px;margin:auto}
@media(max-width:900px){main{grid-template-columns:1fr}}
.box{background:var(--paper);border:1px solid var(--line);border-radius:6px;padding:16px}
#drop{border:2px dashed #8fa3b0;border-radius:6px;padding:26px 12px;text-align:center;color:var(--mute);cursor:pointer}
#drop.on{border-color:var(--blue);background:#eef3fb;color:var(--ink)}#drop b{display:block;color:var(--ink);word-break:break-all}
label{display:block;margin:12px 0 3px;font-weight:600;font-size:14px}select,input{width:100%;padding:8px;border:1px solid var(--line);border-radius:4px;font:inherit;background:#fff}
.row{display:grid;grid-template-columns:1fr 1fr 1fr;gap:8px}small{color:var(--mute)}
button{width:100%;margin-top:16px;padding:12px;border:0;border-radius:5px;background:var(--blue);color:#fff;font:600 16px inherit;cursor:pointer}
button:disabled{background:#8c9aa5;cursor:wait}:focus-visible{outline:3px solid #f0b429;outline-offset:2px}
.top{display:flex;align-items:center;gap:10px;margin-bottom:8px}.top h2{margin:0;font-size:17px}
#badge{padding:2px 10px;border-radius:12px;background:#dfe6ea;font-size:13px}#badge.run{background:#fff3cd}#badge.done{background:#d8f0dd}#badge.error{background:#f8d7d3}
#log{background:#0f1a22;color:#cfe0ea;font:13px/1.55 Consolas,"Cascadia Mono",monospace;padding:12px;border-radius:5px;height:340px;overflow:auto;white-space:pre-wrap;margin:0}
#log .err{color:#ff8a7a}#log .warn{color:#f2c46d}#log .head{color:#7fc4ff;font-weight:700}
#diag{margin-top:10px}#diag li{margin:3px 0}#diag .bad{color:var(--bad)}#res{margin-top:20px;display:none}
#res img.sheet{width:100%;border:1px solid var(--line);border-radius:4px}pre.rep{background:#f3f6f8;padding:12px;border-radius:5px;white-space:pre-wrap;font:13px/1.5 Consolas,monospace}
#crops{display:grid;grid-template-columns:repeat(auto-fill,minmax(120px,1fr));gap:8px}#crops img{width:100%;border:1px solid var(--line);border-radius:3px}
main>*{min-width:0}#log{overflow-x:auto}.mini{width:auto;margin:0 0 0 8px;padding:6px 10px;font-size:13px}
.fin{display:flex;align-items:baseline;gap:14px;flex-wrap:wrap;padding:12px 14px;border-radius:6px;margin:10px 0;border:1px solid var(--line)}.fin b{font:700 28px Consolas,monospace;letter-spacing:1px}.fin.ok{background:#e3f4e8;border-color:#8ccaa0}.fin.part{background:#fff6dc;border-color:#e3c26b}.fin.none{background:#eef1f3}
#rows .r{display:grid;grid-template-columns:150px 150px 1fr;gap:10px;align-items:center;padding:8px 0;border-bottom:1px solid var(--line)}#rows img{width:100%;border-radius:3px;border:1px solid var(--line)}
.txt{font:700 20px Consolas,monospace;display:block;word-break:break-all}.st{display:inline-block;padding:1px 8px;border-radius:10px;font-size:12px;margin-right:8px}.st.ok{background:#d8f0dd}.st.part{background:#fff3cd}.st.none{background:#e6eaed}
[hidden]{display:none!important}#cv{max-width:100%;border:1px solid var(--line);border-radius:4px;cursor:crosshair;margin-top:8px}
a{color:var(--blue)}</style></head><body>
<header style="position:relative"><a href="http://127.0.0.1:8800/" style="position:absolute;right:28px;top:18px;color:#fff;border:1px solid rgba(255,255,255,.6);padding:6px 14px;border-radius:4px;text-decoration:none;font-size:14px">&larr; Về cổng SmartPort</a><h1>Kiểm tra mô hình trên video</h1><p>Thả video, bấm kiểm tra: video được cắt khung, chạy mô hình, rồi hiện nhật ký và kết quả.</p></header>
<main><section class="box"><div id="drop" tabindex="0">Thả video hoặc ảnh vào đây, hoặc bấm để chọn<b id="fname"></b></div><input id="file" type="file" accept="video/*,image/*,.mp4,.avi,.mov,.mkv,.jpg,.jpeg,.png" hidden><div id="imgtools" hidden><canvas id="cv"></canvas><div id="selinfo" style="font-size:13px;margin:6px 0"></div><small>Kéo chuột trên ảnh để chọn vùng cần kiểm tra (không chọn thì kiểm tra cả ảnh).</small><div class="row" style="grid-template-columns:1fr 1fr;margin-top:8px"><div><label for="zoom" style="margin-top:0">Phóng vùng chọn</label><select id="zoom"><option value="1" selected>x1 (giữ nguyên điểm ảnh)</option><option value="2">x2</option><option value="3">x3</option></select></div><div style="align-self:end"><button class="mini" id="clr" type="button" style="margin:0;width:100%">Bỏ vùng chọn</button></div></div></div>
<label for="model">Mô hình</label><select id="model"></select><input id="mpath" placeholder="hoặc gõ đường dẫn tới best.pt / .onnx" style="margin-top:6px">
<label for="backend">Loại mô hình</label><select id="backend"><option value="ultralytics">Ultralytics (.pt hoặc .onnx xuất từ Ultralytics)</option><option value="onnx">ONNX có NMS sẵn (model biển số cũ)</option></select>
<div class="row"><div><label for="imgsz">Cỡ ảnh</label><input id="imgsz" type="number" value="960"></div><div><label for="fps">Khung/giây</label><input id="fps" type="number" value="3" step="0.5"></div><div><label for="conf">Ngưỡng</label><input id="conf" type="number" value="0.25" step="0.05"></div></div>
<small>Cỡ ảnh phải bằng cỡ lúc train. Ngưỡng thấp thì ra nhiều vùng hơn.</small>
<label><input id="track" type="checkbox" style="width:auto"> Gán ID theo dõi từng xe</label>
<label><input id="read" type="checkbox" style="width:auto" checked> Đọc chữ trên vùng số container (mốc tạm)</label>
<label><input id="cut" type="checkbox" style="width:auto" checked> Lưu ảnh cắt từ video</label>
<button id="go" disabled>Kiểm tra</button></section>
<section><div class="box"><div class="top"><h2>Nhật ký</h2><span id="badge">chưa chạy</span><a id="dl" href="#" style="margin-left:auto;display:none">Tải nhật ký</a></div><pre id="log">Chọn một video để bắt đầu.</pre>
<div id="diag"></div></div>
<div id="res" class="box"><h2 style="margin-top:0">Kết quả</h2><pre class="rep" id="rep"></pre><div id="final"></div><div class="top"><h3 style="margin:0">Từng ảnh: một ảnh, một chữ</h3><button class="mini" id="o1">Mở thư mục ảnh cắt</button><button class="mini" id="o2">Mở thư mục ảnh đã xử lý</button></div><div id="rows"></div><p><a id="vid" href="#" download>Tải video đã vẽ khung</a> (mở bằng VLC hoặc Windows Media Player)</p><img class="sheet" id="sheet" alt="Các khung mẫu có khung và nhãn"><h3>Vùng cắt tin cậy nhất</h3><div id="crops"></div></div></section></main>
<script>
const $=s=>document.querySelector(s);let file=null,n=0,timer=null,img=null,sel=null,K=1,drag=null;
fetch('/api/models').then(r=>r.json()).then(m=>{$('#model').innerHTML=m.map(x=>`<option>${x}</option>`).join('')||'<option value="">(chưa thấy model, gõ đường dẫn bên dưới)</option>'});
const pick=f=>{if(!f)return;file=f;img=null;$('#imgtools').hidden=true;if(f.type.startsWith('image/'))showImg(f);$('#fname').textContent=f.name+' ('+(f.size/1e6).toFixed(1)+' MB)';$('#go').disabled=false};
$('#drop').onclick=()=>$('#file').click();$('#file').onchange=e=>pick(e.target.files[0]);
$('#drop').ondragover=e=>{e.preventDefault();$('#drop').classList.add('on')};$('#drop').ondragleave=()=>$('#drop').classList.remove('on');
$('#drop').ondrop=e=>{e.preventDefault();$('#drop').classList.remove('on');pick(e.dataTransfer.files[0])};
const RULES=[[/CUDA out of memory|OutOfMemory/i,'Hết bộ nhớ GPU: giảm cỡ ảnh (ví dụ 800) hoặc đóng ứng dụng đang dùng card NVIDIA.'],
[/No module named|Thiếu thư viện/,'Thiếu thư viện: chạy pip install ultralytics opencv-python-headless.'],[/Không mở được video/,'Không đọc được video: thử video .mp4, hoặc quay lại bằng điện thoại.'],
[/CUDA dùng được: False/,'PyTorch chưa dùng GPU nên chạy chậm: cài lại bản có CUDA.'],[/không phát hiện gì/,'Mô hình không thấy vùng nào: hạ ngưỡng xuống 0.1, kiểm tra cỡ ảnh bằng cỡ lúc train và đúng file model.'],
[/FileNotFoundError|No such file|does not exist/i,'Không thấy file model: kiểm tra đường dẫn model.'],[/uint8|cct_s_v2/,'Chọn nhầm file: cct_s_v2_global.onnx là bộ đọc chữ biển số, không phải mô hình tìm vùng. Chọn best.pt đã train hoặc plate_yolo.onnx.'],
[/cublasLt64|CUDAExecutionProvider not available/,'onnxruntime-gpu thiếu thư viện CUDA 13 nên tự chạy bằng CPU (không phải lỗi). File best.pt không dùng onnxruntime nên không bị ảnh hưởng.'],[/Traceback|Error/,'Có lỗi chương trình: chép đoạn lỗi cuối nhật ký gửi cho Claude.']];
function diag(t){const h=RULES.filter(r=>r[0].test(t)).map(r=>`<li class="bad">${r[1]}</li>`);$('#diag').innerHTML='<b>Chẩn đoán</b><ul>'+(h.join('')||'<li>Không thấy dấu hiệu lỗi trong nhật ký.</li>')+'</ul>'}
function add(l){const d=document.createElement('div');d.textContent=l;if(/Traceback|Error|LỖI|lỗi|KHÔNG/.test(l))d.className='err';else if(/CẢNH BÁO|WARNING|Warning|bỏ qua/.test(l))d.className='warn';else if(/^---/.test(l))d.className='head';$('#log').appendChild(d);$('#log').scrollTop=1e9}
function badge(s){const b=$('#badge');b.className=s;b.textContent={run:'đang chạy',done:'xong',error:'có lỗi'}[s]||s}
$('#go').onclick=async()=>{$('#go').disabled=true;let body=file,fname=file.name;if(img){body=await cropBlob();fname='anh.jpg'}$('#log').innerHTML='';$('#res').style.display='none';$('#diag').innerHTML='';n=0;badge('run');add('--- Đang gửi lên máy chạy ('+(body.size/1e6).toFixed(1)+' MB)');
const p=new URLSearchParams({filename:fname,model:$('#mpath').value||$('#model').value,backend:$('#backend').value,imgsz:$('#imgsz').value,fps:$('#fps').value,conf:$('#conf').value,track:$('#track').checked?'1':'0',read:$('#read').checked?'1':'0',cut:$('#cut').checked?'1':'0'});
const r=await fetch('/api/run?'+p,{method:'POST',body:body});if(!r.ok){add('LỖI: '+(await r.text()));badge('error');$('#go').disabled=false;return}
timer=setInterval(async()=>{const s=await (await fetch('/api/status?from='+n)).json();s.lines.forEach(add);n=s.n;
if(s.state!=='running'){clearInterval(timer);badge(s.state);$('#go').disabled=false;diag($('#log').innerText);const x=s.result||{};if(x.log){$('#dl').href=x.log;$('#dl').style.display='inline'}
if(x.sheet){window.RUN=x.run;loadRows(x.data);$('#res').style.display='block';$('#rep').textContent=x.report;$('#sheet').src=x.sheet+'?t='+Date.now();$('#vid').href=x.video;$('#crops').innerHTML=(x.crops||[]).map(c=>`<img src="${c}" loading="lazy" alt="vùng cắt">`).join('')}}},700)};
function showImg(f){img=new Image();img.onload=()=>{const cv=$('#cv');K=Math.min(1,560/img.width);cv.width=Math.round(img.width*K);cv.height=Math.round(img.height*K);sel=null;paint();info();$('#imgtools').hidden=false};img.src=URL.createObjectURL(f)}
function paint(){const cv=$('#cv'),g=cv.getContext('2d');g.drawImage(img,0,0,cv.width,cv.height);if(sel){g.fillStyle='rgba(0,0,0,.4)';g.fillRect(0,0,cv.width,cv.height);const[x,y,w,h]=sel;g.drawImage(img,x/K,y/K,w/K,h/K,x,y,w,h);g.strokeStyle='#f0b429';g.lineWidth=2;g.strokeRect(x,y,w,h)}}
function info(){const w=Math.round(sel?sel[2]/K:img.width),h=Math.round(sel?sel[3]/K:img.height);$('#selinfo').innerHTML=(sel?'Vùng chọn: ':'Cả ảnh: ')+w+'×'+h+' điểm ảnh (ảnh gốc).'+((w<250&&h<250)?' <b style="color:#b7791f">Vùng nhỏ: phóng to không tạo thêm chi tiết, chữ có thể không đọc được. Nên chụp gần hơn hoặc cắt từ ảnh độ phân giải cao.</b>':'')}
function pos(e){const cv=$('#cv'),r=cv.getBoundingClientRect();return[(e.clientX-r.left)*cv.width/r.width,(e.clientY-r.top)*cv.height/r.height]}
$('#cv').onmousedown=e=>{drag=pos(e);sel=null};
$('#cv').onmousemove=e=>{if(!drag)return;const p=pos(e);sel=[Math.min(drag[0],p[0]),Math.min(drag[1],p[1]),Math.abs(p[0]-drag[0]),Math.abs(p[1]-drag[1])];paint();info()};
window.onmouseup=()=>{if(drag){drag=null;if(sel&&(sel[2]<8||sel[3]<8))sel=null;paint();info()}};
$('#clr').onclick=()=>{sel=null;paint();info()};
function cropBlob(){return new Promise(res=>{const z=sel?+$('#zoom').value:1,r=sel?[sel[0]/K,sel[1]/K,sel[2]/K,sel[3]/K]:[0,0,img.width,img.height],c=document.createElement('canvas');c.width=Math.round(r[2]*z);c.height=Math.round(r[3]*z);const g=c.getContext('2d');g.imageSmoothingQuality='high';g.drawImage(img,r[0],r[1],r[2],r[3],0,0,c.width,c.height);c.toBlob(b=>res(b),'image/jpeg',0.95)})}
const ST={'HỢP LỆ':'ok','CHƯA XÁC NHẬN':'part','MỘT PHẦN':'part'};
async function loadRows(u){if(!u)return;const d=await (await fetch(u)).json();const b='/files/'+RUN+'/out/';
$('#final').innerHTML=(d.final&&d.final.length)?d.final.map(f=>`<div class="fin ${f.votes>=2?'ok':'part'}"><span>${f.group}</span><b>${f.code}</b><small>${f.note}</small></div>`).join(''):'<div class="fin none"><b>Chưa có mã hợp lệ</b><small>Xem từng ảnh bên dưới và nhật ký</small></div>';
$('#rows').innerHTML=(d.frames||[]).map(r=>`<div class="r">${d.cut?`<a href="${b}frames_cut/${r.file}" target="_blank"><img loading="lazy" src="${b}frames_cut/${r.file}" alt="ảnh cắt"></a>`:'<span></span>'}<a href="${b}frames_processed/${r.file}" target="_blank"><img loading="lazy" src="${b}frames_processed/${r.file}" alt="ảnh đã xử lý"></a><div><b class="txt">${r.text||'—'}</b><span class="st ${ST[r.status]||'none'}">${r.status}</span><small>t=${r.t}s, ${r.boxes} vùng</small></div></div>`).join('')}
const op=d=>async()=>{const r=await (await fetch(`/api/open?run=${RUN}&dir=${d}`)).json();alert(r.path?'Thư mục: '+r.path:'Không mở được')};
$('#o1').onclick=op('cut');$('#o2').onclick=op('processed');
$('#model').onchange=()=>{const v=$('#model').value;if(/plate_yolo/.test(v)){$('#backend').value='onnx';$('#imgsz').value=320}else if(/\.pt$/.test(v)){$('#backend').value='ultralytics';$('#imgsz').value=960}};
</script></body></html>'''

if __name__ == "__main__":
    srv = ThreadingHTTPServer(("127.0.0.1", PORT), H)
    print(f"Giao diện kiểm tra video đang chạy tại http://127.0.0.1:{PORT}  (nhấn Ctrl+C để tắt)")
    threading.Timer(1.0, lambda: webbrowser.open(f"http://127.0.0.1:{PORT}")).start()
    try: srv.serve_forever()
    except KeyboardInterrupt: print("Đã tắt.")
