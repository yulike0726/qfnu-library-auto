# -*- coding: utf-8 -*-
"""CAS sign-in for the library.

Two paths:
  * fast path   - reuse the browser's CASTGC cookie (no captcha at all);
  * browser path- drive Edge over CDP, solve the slide captcha and submit the form.

The library's phpCAS expects the ticket to be validated by
http://ids.qfnu.edu.cn:80/authserver, and it keeps state in its own PHP session,
so the ticket must be exchanged in three steps (see exchange()).
"""
import json
import os
import re
import subprocess
import time

import requests
import websocket

from . import settings

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/157.0.0.0 Safari/537.36")


# --------------------------------------------------------------------------- CDP
class CDP:
    def __init__(self, port=9222, target="page"):
        self.port = port
        self.ws = None
        self.mid = 0
        self.target = target
        self._connect()

    def _connect(self):
        for _ in range(20):
            try:
                lst = requests.get(f"http://127.0.0.1:{self.port}/json/list", timeout=3).json()
                cand = [t for t in lst if t.get("type") == self.target and t.get("webSocketDebuggerUrl")]
                if cand:
                    self.ws = websocket.create_connection(cand[0]["webSocketDebuggerUrl"], timeout=30)
                    return
            except Exception:
                pass
            time.sleep(0.5)
        raise RuntimeError("no CDP page target on port %s" % self.port)

    def call(self, method, **params):
        self.mid += 1
        mid = self.mid
        self.ws.send(json.dumps({"id": mid, "method": method, "params": params}))
        while True:
            msg = json.loads(self.ws.recv())
            if msg.get("id") == mid:
                if "error" in msg:
                    raise RuntimeError(f"{method}: {msg['error']}")
                return msg.get("result", {})

    def js(self, expr, await_promise=True, timeout_ms=60000):
        r = self.call("Runtime.evaluate", expression=expr, awaitPromise=await_promise,
                      returnByValue=True, timeout=timeout_ms)
        if r.get("exceptionDetails"):
            raise RuntimeError("js error: %s" % json.dumps(r["exceptionDetails"])[:400])
        return r.get("result", {}).get("value")

    def cookies(self):
        self.call("Network.enable")
        return self.call("Network.getAllCookies").get("cookies", [])

    def goto(self, url):
        self.call("Page.enable")
        self.call("Page.navigate", url=url)

    def close(self):
        try:
            self.ws.close()
        except Exception:
            pass


def launch_edge(cfg):
    exe = cfg["edge_exe"]
    if not os.path.exists(exe):
        for p in (r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
                  os.path.expandvars(r"%LOCALAPPDATA%\Microsoft\Edge\Application\msedge.exe")):
            if os.path.exists(p):
                exe = p
                break
    subprocess.Popen([exe, f"--remote-debugging-port={cfg['cdp_port']}",
                      f"--user-data-dir={cfg['edge_profile']}", "--disable-extensions",
                      "--no-first-run", "--no-default-browser-check", "about:blank"],
                     creationflags=0x00000008)


def reset_edge(cfg):
    """Kill a wedged Edge that owns this profile (CDP connects but never answers)."""
    prof = cfg["edge_profile"]
    ps = ("Get-CimInstance Win32_Process -Filter \"Name='msedge.exe'\" | "
          "Where-Object { $_.CommandLine -like '*%s*' } | "
          "ForEach-Object { Stop-Process -Id $_.ProcessId -Force "
          "-ErrorAction SilentlyContinue }" % prof)
    try:
        subprocess.run(["powershell", "-NoProfile", "-Command", ps],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                       timeout=40)
    except Exception:
        pass
    time.sleep(2)


def wait_port(port, secs=25):
    for _ in range(int(secs / 0.5)):
        try:
            if requests.get(f"http://127.0.0.1:{port}/json/version", timeout=2).ok:
                return True
        except Exception:
            pass
        time.sleep(0.5)
    return False


SOLVER = r"""
(async () => {
  const sleep = (ms) => new Promise(r => setTimeout(r, ms));
  const $ = window.jQuery;
  let inst = $('#sliderDiv').data('lgb.SliderCaptcha');
  if (!inst) return {ok:false, why:'no slider'};
  const W = inst.canvas.width, H = inst.canvas.height;
  const bg = inst.canvasCtx.getImageData(0,0,W,H).data;
  const blk = inst.blockCtx.getImageData(0,0,W,H).data;
  const gray=(d,i)=>0.299*d[i]+0.587*d[i+1]+0.114*d[i+2];
  const sobel=(src)=>{
    const out=new Float32Array(W*H);
    for(let y=1;y<H-1;y++)for(let x=1;x<W-1;x++){
      const at=(xx,yy)=>gray(src,(yy*W+xx)*4);
      const gx=-at(x-1,y-1)-2*at(x-1,y)-at(x-1,y+1)+at(x+1,y-1)+2*at(x+1,y)+at(x+1,y+1);
      const gy=-at(x-1,y-1)-2*at(x,y-1)-at(x+1,y-1)+at(x-1,y+1)+2*at(x,y+1)+at(x+1,y+1);
      out[y*W+x]=Math.hypot(gx,gy);
    }
    return out;
  };
  let x0=1e9,x1=-1,y0=1e9,y1=-1;
  for(let y=0;y<H;y++)for(let x=0;x<W;x++){
    if(blk[(y*W+x)*4+3]>20){if(x<x0)x0=x;if(x>x1)x1=x;if(y<y0)y0=y;if(y>y1)y1=y;}
  }
  const pw=x1-x0+1, ph=y1-y0+1;
  const bgG=sobel(bg), blkG=sobel(blk);
  const mask=new Float32Array(pw*ph);
  let msum=0,mn=0;
  for(let y=0;y<ph;y++)for(let x=0;x<pw;x++){
    if(blk[((y+y0)*W+(x+x0))*4+3]>128){mask[y*pw+x]=1;msum+=blkG[(y+y0)*W+(x+x0)];mn++;}
  }
  const bmean=msum/Math.max(mn,1);
  const tmpl=new Float32Array(pw*ph);
  let tn=0;
  for(let i=0;i<pw*ph;i++){
    if(mask[i]){tmpl[i]=blkG[((Math.floor(i/pw)+y0)*W+(i%pw)+x0)]-bmean;tn+=tmpl[i]*tmpl[i];}
  }
  let best=-2,bestX=-1;
  for(let sx=0;sx<=W-pw;sx++){
    let num=0,sm=0,sn=0;
    for(let y=0;y<ph;y++)for(let x=0;x<pw;x++){
      if(!mask[y*pw+x])continue;
      const v=bgG[(y+y0)*W+(sx+x)];
      num+=tmpl[y*pw+x]*v;sm+=v;sn+=v*v;
    }
    const den=Math.sqrt(tn*(sn-sm*sm/mn))+1e-6;
    const sc=num/den;
    if(sc>best){best=sc;bestX=sx;}
  }
  const sl=$('#sliderDiv .slider');
  const ax=sl.offset().left+20, ay=sl.offset().top+20;
  const ev=(t,x,y,el)=>el.dispatchEvent(new MouseEvent(t,{clientX:x,clientY:y,bubbles:true,cancelable:true,view:window}));
  ev('mousedown',ax,ay,sl[0]);
  const N=45, dt=22;
  let prev=0;
  for(let i=1;i<=N;i++){
    const p=i/N;
    const dx=Math.round(bestX*(1-Math.pow(1-p,2.0)));
    if(dx<=prev)continue;
    prev=dx;
    await sleep(dt);
    ev('mousemove',ax+dx,ay+Math.round(2*Math.sin(p*9)),document);
  }
  await sleep(30);
  ev('mouseup',ax+bestX,ay,document);
  await sleep(1000);
  return {ok:/success/.test($('#sliderDiv .sliderContainer').attr('class')||''),
          score:+best.toFixed(3), move:bestX,
          submitted:!!window.__submitted};
})()
"""


# ----------------------------------------------------------------------- ticket
def exchange(cfg, ticket):
    """Run the three-step phpCAS dance; return the library `cas` code."""
    s = requests.Session()
    s.headers.update({"User-Agent": UA, "Referer": cfg["lib_base"] + "/h5/index.html"})
    s.get(cfg["lib_base"] + "/api/cas/cas", allow_redirects=False, timeout=20)
    s.get(cfg["lib_base"] + "/api/cas/cas", params={"ticket": ticket},
          allow_redirects=False, timeout=20)
    r = s.get(cfg["lib_base"] + "/api/cas/cas", allow_redirects=False, timeout=20)
    m = re.search(r"cas=([0-9a-f]+)", r.headers.get("Location", ""))
    if not m:
        m = re.search(r"cas=([0-9a-f]+)", r.text)
    return m.group(1) if m else ""


def ticket_from_castgc(cfg, castgc):
    s = requests.Session()
    s.headers.update({"User-Agent": UA})
    s.cookies.set("CASTGC", castgc, domain="ids.qfnu.edu.cn")
    r = s.get(cfg["cas_base"] + "/authserver/login", params={"service": cfg["service"]},
              allow_redirects=False, timeout=20)
    if r.status_code != 302:
        return ""
    m = re.search(r"[?&]ticket=([^&]+)", r.headers.get("Location", ""))
    return m.group(1) if m else ""


def castgc_from_edge(cfg, cdp=None):
    own = cdp is None
    if own:
        if not wait_port(cfg["cdp_port"], 3):
            launch_edge(cfg)
            if not wait_port(cfg["cdp_port"], 30):
                return ""
        cdp = CDP(port=cfg["cdp_port"])
    try:
        for c in cdp.cookies():
            if c["name"] == "CASTGC" and "ids.qfnu.edu.cn" in c["domain"]:
                return c["value"]
    finally:
        if own:
            cdp.close()
    return ""


def browser_login(cfg, tries=3):
    """Drive Edge: fill the form, solve the slider, let the page submit itself."""
    if not wait_port(cfg["cdp_port"], 3):
        launch_edge(cfg)
        if not wait_port(cfg["cdp_port"], 30):
            raise RuntimeError("Edge CDP did not start")
    cdp = CDP(port=cfg["cdp_port"])
    try:
        url = (cfg["cas_base"] + "/authserver/login?service="
               + requests.utils.quote(cfg["service"], safe=""))
        cdp.goto(url)
        time.sleep(2)
        for _ in range(20):
            if cdp.js("!!document.querySelector('#username')"):
                break
            time.sleep(0.5)

        for attempt in range(1, tries + 1):
            # fill credentials and force the slider branch
            cdp.js("""(() => {
                const u = document.querySelector('#username');
                const p = document.querySelector('#password');
                u.value = %s; p.value = %s;
                u.dispatchEvent(new Event('input', {bubbles:true}));
                p.dispatchEvent(new Event('input', {bubbles:true}));
                window.__submitted = false;
                try { if (!window.__origSubmit) { window.__origSubmit = jQuery.fn.submit;
                        jQuery.fn.submit = function(){ window.__submitted = true; return this; }; } } catch(e){}
                window.needCaptcha = true;
                return true;
            })()""" % (json.dumps(cfg["account"]), json.dumps(cfg["password"])))
            # load the widget, then click login -> dzlogin opens the slider
            cdp.js("""(async () => {
                if (!jQuery('#sliderDiv').data('lgb.SliderCaptcha')) {
                    const html = await jQuery.get('/authserver/common/toSliderCaptcha.htl');
                    jQuery('#sliderCaptchaDiv').html(html);
                    await new Promise(r => setTimeout(r, 1200));
                }
                return true;
            })()""")
            cdp.js("document.querySelector('#login_submit').click(); true")
            time.sleep(1.2)
            for _ in range(20):
                if cdp.js("!!(window.jQuery && jQuery('#sliderDiv').data('lgb.SliderCaptcha'))"):
                    break
                time.sleep(0.5)
            res = cdp.js(SOLVER) or {}
            if res.get("ok"):
                # dzlogin would call $('.loginFromClass').submit(), which we blocked;
                # submit the real form ourselves with the salted password.
                cdp.js("""(() => {
                    const form = document.getElementById('pwdFromId');
                    const pwd = document.querySelector('#password');
                    const salt = document.querySelector('#pwdEncryptSalt').value;
                    let sp = document.querySelector('#saltPassword');
                    if (!sp) { sp = document.createElement('input'); sp.type = 'hidden';
                               sp.id = 'saltPassword'; sp.name = 'saltPassword';
                               form.appendChild(sp); }
                    sp.value = encryptPassword(pwd.value, salt);
                    pwd.disabled = true;
                    form.submit();
                    return sp.value.length;
                })()""")
                time.sleep(3)
                castgc = castgc_from_edge(cfg, cdp)
                if castgc:
                    return castgc
            # refresh captcha and retry
            cdp.js("try{openSliderCaptcha(2);}catch(e){}; true")
            time.sleep(1)
        return ""
    finally:
        cdp.close()