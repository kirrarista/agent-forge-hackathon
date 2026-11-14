"""Local activity dashboard: python -m obs.dashboard

Stdlib only, read-only, binds 127.0.0.1. Complements AgentField's workflow graph
with bot-level activity (runs, buttons, stage timings, errors). All scraped
strings are rendered via textContent, never innerHTML.
"""
from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

import obs

HTML = """<!doctype html><html><head><meta charset="utf-8"><title>Lowball activity</title>
<style>
 body{font:14px/1.5 system-ui,sans-serif;margin:0;background:#0f1115;color:#e6e6e6}
 header{padding:12px 20px;background:#171a21;display:flex;gap:12px;align-items:center}
 h1{font-size:16px;margin:0}
 .dot{width:9px;height:9px;border-radius:50%;background:#666;display:inline-block}
 .dot.on{background:#3fb950}
 main{padding:16px 20px;max-width:1100px;margin:0 auto}
 .cards{display:flex;gap:12px;flex-wrap:wrap;margin-bottom:16px}
 .card{background:#171a21;border:1px solid #262b36;border-radius:8px;padding:10px 16px;min-width:88px}
 .card b{display:block;font-size:22px}
 .card span{color:#9aa4b2;font-size:12px}
 table{width:100%;border-collapse:collapse;margin-bottom:8px}
 th,td{text-align:left;padding:6px 8px;border-bottom:1px solid #262b36;font-size:13px}
 th{color:#9aa4b2;font-weight:600}
 h2{font-size:12px;color:#9aa4b2;text-transform:uppercase;letter-spacing:.05em;margin:18px 0 8px}
 #feed{font:12px/1.7 ui-monospace,monospace;background:#171a21;border:1px solid #262b36;border-radius:8px;padding:10px;max-height:340px;overflow:auto}
 .ev{white-space:pre-wrap}
 .k-run_started{color:#58a6ff}.k-run_finished{color:#3fb950}.k-run_failed{color:#f85149}
 .k-stage{color:#d29922}.k-button{color:#bc8cff}.k-bot_started{color:#9aa4b2}
 .empty{color:#9aa4b2;padding:16px;text-align:center}
</style></head><body>
<header><h1>🔎 Lowball activity</h1><span class="dot" id="dot"></span><span id="status">connecting…</span></header>
<main>
 <div class="cards" id="cards"></div>
 <h2>Recent runs</h2>
 <table><thead><tr><th>Time</th><th>Op</th><th>Query</th><th>Mode</th><th>Status</th><th>Duration</th><th>🚩</th></tr></thead><tbody id="runs"></tbody></table>
 <div class="empty" id="runsEmpty" hidden>No runs yet — send /buy in Telegram.</div>
 <h2>Event feed</h2>
 <div id="feed"></div>
</main>
<script>
const $=id=>document.getElementById(id);
function el(tag,cls,text){const e=document.createElement(tag);if(cls)e.className=cls;if(text!=null)e.textContent=text;return e;}
function card(label,value){const c=el('div','card');c.append(el('b',null,String(value)),el('span',null,label));return c;}
async function poll(){
 try{
  const s=await (await fetch('/api/state')).json();
  $('dot').className='dot'+(s.online?' on':'');
  $('status').textContent=s.online?'bot online':'waiting for bot';
  const c=s.counters;
  $('cards').replaceChildren(card('runs',c.runs),card('buy',c.buy),card('sell',c.sell),
   card('🚩 scams',c.scams),card('✅ approvals',c.approvals),card('💬 offers',c.offers),card('⚠️ errors',c.errors));
  const tb=$('runs');tb.replaceChildren();$('runsEmpty').hidden=s.runs.length>0;
  for(const r of s.runs){
   const tr=el('tr');
   const t=r.started_ts?new Date(r.started_ts*1000).toLocaleTimeString():'—';
   const dur=r.duration_ms!=null?(r.duration_ms/1000).toFixed(1)+'s':'—';
   [t,r.op||'',(r.query||'').slice(0,40),r.mode||'',r.status||'',dur,String(r.scams||0)]
    .forEach(v=>tr.append(el('td',null,v)));
   tb.append(tr);
  }
  const feed=$('feed');feed.replaceChildren();
  if(!s.feed.length)feed.append(el('div','empty','No events yet.'));
  for(const e of s.feed){
   const d=e.data||{},p=[e.kind];
   if(d.stage)p.push(d.stage+(d.duration_ms!=null?' '+d.duration_ms+'ms':''));
   if(d.op)p.push(d.op);
   if(d.query)p.push('"'+d.query+'"');
   if(d.action)p.push(d.action+(d.ok===false?' (dup)':''));
   if(d.error)p.push(d.error);
   feed.append(el('div','ev k-'+e.kind,p.join(' · ')));
  }
 }catch(err){$('status').textContent='dashboard error: '+err;}
}
poll();setInterval(poll,2000);
</script></body></html>"""


def build_state(limit: int = 500) -> dict:
    events = obs.read_events(limit)
    s = obs.summarize(events)
    return {
        "counters": s["counters"],
        "runs": s["runs"],
        "feed": events[-50:][::-1],
        "online": any(e.get("kind") == "bot_started" for e in events),
        "db": obs.LOG.exists(),
    }


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):  # silence per-request stderr spam
        pass

    def _send(self, code: int, body: bytes, ctype: str = "application/json") -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        path = urlparse(self.path).path
        if path == "/":
            self._send(200, HTML.encode("utf-8"), "text/html; charset=utf-8")
        elif path == "/api/state":
            body = json.dumps(build_state(), ensure_ascii=False, default=str).encode("utf-8")
            self._send(200, body)
        else:
            self._send(404, b'{"error":"not found"}')


def main() -> None:
    server = ThreadingHTTPServer(("127.0.0.1", obs.PORT), Handler)
    print(f"Lowball dashboard: http://localhost:{obs.PORT}  (log: {obs.LOG})")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()