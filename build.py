#!/usr/bin/env python3
"""
Data Centre Daily Report — site builder (lives IN the repo, runs anywhere:
locally or inside a Claude cloud routine).

Reads raw report HTML from source/ and generates the published site:
  source/daily/YYYY-MM-DD.html    -> reports/YYYY-MM-DD.html (+ latest becomes index.html)
  source/weekly/YYYY-MM-DD.html   -> weekly/YYYY-MM-DD.html
  source/monthly/YYYY-MM.html     -> monthly/YYYY-MM.html
Also regenerates archive.html, weekly/index.html, monthly/index.html.

Raw source files must NOT contain a <nav> element — it is injected here.

Usage: python3 build.py   (run from the repo root)
"""
import os, re, datetime, html

ROOT = os.path.dirname(os.path.abspath(__file__))

NAV = """<nav style="max-width:860px;margin:0 auto 24px;display:flex;gap:18px;font-size:14px;
  border-bottom:1px solid #2d333b;padding-bottom:12px;flex-wrap:wrap">
  <a href="{p}index.html" style="color:#58a6ff;text-decoration:none;font-weight:600">Today</a>
  <a href="{p}archive.html" style="color:#8b949e;text-decoration:none">Daily Archive</a>
  <a href="{p}weekly/index.html" style="color:#8b949e;text-decoration:none">Weekly</a>
  <a href="{p}monthly/index.html" style="color:#8b949e;text-decoration:none">Monthly</a>
</nav>"""

PAGE_SHELL = """<!DOCTYPE html><html lang="en"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0"><title>{title}</title>
<style>body{{background:#0d1117;color:#e6edf3;font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;padding:32px 20px}}
.wrap{{max-width:860px;margin:0 auto}}h1{{font-size:24px;margin-bottom:18px}}
ul{{list-style:none}}li{{margin-bottom:10px}}a{{color:#58a6ff;text-decoration:none;font-size:15px}}
a:hover{{text-decoration:underline}}.muted{{color:#8b949e;font-size:14px}}</style></head>
<body>{nav}<div class="wrap"><h1>{title}</h1>{body}</div></body></html>"""

FILTER_CSS = """<style>
#catfilter{display:flex;gap:8px;flex-wrap:wrap;align-items:center;margin-bottom:24px}
#catfilter .flabel{font-size:12px;color:#8b949e;margin-right:2px}
.fbtn{font-size:12px;font-weight:600;padding:4px 12px;border-radius:20px;letter-spacing:.3px;border:1px solid transparent;cursor:pointer;font-family:inherit}
.fbtn:hover{filter:brightness(1.25)}
.fbtn.active{border-color:currentColor}
.fbtn-all{background:rgba(88,166,255,.15);color:#58a6ff}
</style>"""

AUDIO_JS = """<script>
(function(){
  if(document.getElementById('briefaudio'))return;
  var s=document.querySelector('.summary');
  if(!s||!('speechSynthesis'in window))return;
  var btn=document.createElement('button');
  btn.id='listenbtn';btn.textContent='\\u25B6 Listen';
  s.appendChild(btn);
  var u=null,speaking=false;
  function stop(){window.speechSynthesis.cancel();speaking=false;btn.textContent='\\u25B6 Listen';}
  btn.addEventListener('click',function(){
    if(speaking){stop();return;}
    var text=s.textContent.replace('\\u25B6 Listen','').replace(/^\\s*Morning brief:\\s*/,'');
    u=new SpeechSynthesisUtterance('Your data centre morning brief. '+text);
    u.rate=1;u.lang='en-CA';
    var v=window.speechSynthesis.getVoices().filter(function(x){return /en[-_](CA|US)/.test(x.lang)});
    if(v.length)u.voice=v[0];
    u.onend=stop;u.onerror=stop;
    window.speechSynthesis.cancel();
    window.speechSynthesis.speak(u);
    speaking=true;btn.textContent='\\u25A0 Stop';
  });
  window.addEventListener('beforeunload',function(){window.speechSynthesis.cancel();});
})();
</script>"""

AUDIO_CSS = """<style>
#listenbtn{display:block;margin-top:12px;font-size:12.5px;font-weight:600;padding:5px 14px;border-radius:20px;
border:1px solid #2d333b;background:rgba(88,166,255,.15);color:#58a6ff;cursor:pointer;font-family:inherit}
#listenbtn:hover{filter:brightness(1.25)}
</style>"""

FILTER_JS = """<script>
(function(){
  var bar=document.getElementById('catfilter');
  if(!bar)return;
  bar.addEventListener('click',function(e){
    var b=e.target.closest('button');if(!b)return;
    bar.querySelectorAll('button').forEach(function(x){x.classList.remove('active')});
    b.classList.add('active');
    var cat=b.getAttribute('data-cat');
    document.querySelectorAll('.card').forEach(function(c){
      if(cat==='all'){c.style.display='';return;}
      var tags=Array.prototype.map.call(c.querySelectorAll('.tag'),function(t){return t.textContent.trim()});
      c.style.display=tags.indexOf(cat)>=0?'':'none';
    });
  });
})();
</script>"""

def inject_filters(html_text):
    """Add a category filter bar under the morning brief (.summary box).
    Categories are discovered from the tags actually present in the page."""
    cats, seen = [], set()
    for cls, label in re.findall(r'class="tag (t-[a-z]+)"[^>]*>([^<]+)<', html_text):
        label = label.strip()
        if label not in seen:
            seen.add(label)
            cats.append((cls, label))
    if not cats:
        return html_text
    buttons = '<button class="fbtn fbtn-all active" data-cat="all">All</button>'
    buttons += "".join(
        f'<button class="fbtn tag {cls}" data-cat="{html.escape(label)}">{html.escape(label)}</button>'
        for cls, label in cats)
    bar = f'<div id="catfilter"><span class="flabel">Filter:</span>{buttons}</div>'
    # insert after the closing tag of the .summary div (it contains no nested divs)
    m = re.search(r'(<div class="summary">.*?</div>)', html_text, re.S)
    if m:
        out = html_text[:m.end()] + "\n" + bar + html_text[m.end():]
    else:
        m = re.search(r"(</header>)", html_text)
        if not m:
            return html_text
        out = html_text[:m.end()] + "\n" + bar + html_text[m.end():]
    out = out.replace("</head>", FILTER_CSS + "\n" + AUDIO_CSS + "\n</head>", 1)
    out = out.replace("</body>", FILTER_JS + "\n" + AUDIO_JS + "\n</body>", 1)
    return out

PLAYER_CSS = """<style>
#briefaudio{display:flex;align-items:center;gap:12px;margin-top:14px;padding:8px 12px;
background:#0d1117;border:1px solid #2d333b;border-radius:8px}
#briefaudio .pbtn{width:34px;height:34px;border-radius:50%;border:none;cursor:pointer;flex:none;
background:rgba(88,166,255,.15);color:#58a6ff;font-size:13px;font-family:inherit}
#briefaudio .pbtn:hover{filter:brightness(1.3)}
#briefaudio .ptrack{flex:1;height:6px;border-radius:3px;background:#2d333b;cursor:pointer;position:relative}
#briefaudio .pfill{height:100%;width:0%;border-radius:3px;background:#58a6ff}
#briefaudio .ptime{font-size:12px;color:#8b949e;min-width:72px;text-align:right;font-variant-numeric:tabular-nums}
#briefaudio .prate{border:1px solid #2d333b;background:none;color:#8b949e;font-size:11.5px;font-weight:600;
padding:3px 8px;border-radius:12px;cursor:pointer;font-family:inherit;flex:none}
#briefaudio .prate:hover{color:#58a6ff;border-color:#58a6ff}
</style>"""

PLAYER_JS = """<script>
(function(){
  var w=document.getElementById('briefaudio');
  if(!w)return;
  var a=w.querySelector('audio'),btn=w.querySelector('.pbtn'),
      track=w.querySelector('.ptrack'),fill=w.querySelector('.pfill'),
      time=w.querySelector('.ptime'),rate=w.querySelector('.prate');
  var rates=[1,1.25,1.5,2],ri=0;
  function fmt(s){if(!isFinite(s))return'0:00';s=Math.floor(s);return Math.floor(s/60)+':'+('0'+s%60).slice(-2);}
  function upd(){fill.style.width=(a.duration?100*a.currentTime/a.duration:0)+'%';
    time.textContent=fmt(a.currentTime)+' / '+fmt(a.duration);}
  btn.addEventListener('click',function(){a.paused?a.play():a.pause();});
  a.addEventListener('play',function(){btn.textContent='\\u275A\\u275A';});
  a.addEventListener('pause',function(){btn.textContent='\\u25B6';});
  a.addEventListener('ended',function(){btn.textContent='\\u25B6';a.currentTime=0;});
  a.addEventListener('timeupdate',upd);
  a.addEventListener('loadedmetadata',upd);
  track.addEventListener('click',function(e){
    var r=track.getBoundingClientRect();
    if(a.duration)a.currentTime=a.duration*(e.clientX-r.left)/r.width;});
  rate.addEventListener('click',function(){ri=(ri+1)%rates.length;a.playbackRate=rates[ri];
    rate.textContent=rates[ri]+'\\u00D7';});
})();
</script>"""

def inject_audio_player(html_text, date_iso, depth):
    """Embed a themed MP3 player under the morning brief when audio/<date>.mp3 exists."""
    if not date_iso or not os.path.exists(os.path.join(ROOT, "audio", f"{date_iso}.mp3")):
        return html_text
    src = "../" * depth + f"audio/{date_iso}.mp3"
    player = (f'<div id="briefaudio">'
              f'<button class="pbtn" aria-label="Play">▶</button>'
              f'<div class="ptrack"><div class="pfill"></div></div>'
              f'<span class="ptime">0:00 / 0:00</span>'
              f'<button class="prate" aria-label="Playback speed">1×</button>'
              f'<audio preload="metadata" src="{src}"></audio></div>')
    m = re.search(r'(<div class="summary">.*?)(</div>)', html_text, re.S)
    if not m:
        return html_text
    out = html_text[:m.end(1)] + player + html_text[m.end(1):]
    out = out.replace("</head>", PLAYER_CSS + "\n</head>", 1)
    out = out.replace("</body>", PLAYER_JS + "\n</body>", 1)
    return out

def inject_nav(html_text, depth=0, audio_date=None):
    nav = NAV.format(p="../" * depth)
    out = re.sub(r"(<body[^>]*>)", r"\1\n" + nav, html_text, count=1)
    out = inject_filters(out)
    return inject_audio_player(out, audio_date, depth)

def list_sources(subdir, pattern):
    d = os.path.join(ROOT, "source", subdir)
    if not os.path.isdir(d):
        return []
    out = []
    for f in sorted(os.listdir(d), reverse=True):
        m = re.match(pattern, f)
        if m:
            out.append((m.group(1), os.path.join(d, f)))
    return out

def build_index_page(title, items, depth, empty_msg):
    if items:
        lis = "\n".join(f'<li><a href="{href}">{html.escape(label)}</a></li>' for label, href in items)
        body = f"<ul>{lis}</ul>"
    else:
        body = f'<p class="muted">{empty_msg}</p>'
    return PAGE_SHELL.format(title=title, nav=NAV.format(p="../" * depth), body=body)

def pretty_date(iso):
    return datetime.date.fromisoformat(iso).strftime("%A, %B %d, %Y").replace(" 0", " ")

def write(relpath, content):
    path = os.path.join(ROOT, relpath)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)

def main():
    dailies = list_sources("daily", r"^(\d{4}-\d{2}-\d{2})\.html$")
    weeklies = list_sources("weekly", r"^(\d{4}-\d{2}-\d{2})\.html$")
    monthlies = list_sources("monthly", r"^(\d{4}-\d{2})\.html$")

    for iso, path in dailies:
        with open(path, encoding="utf-8") as f:
            write(f"reports/{iso}.html", inject_nav(f.read(), depth=1, audio_date=iso))
    if dailies:
        with open(dailies[0][1], encoding="utf-8") as f:
            write("index.html", inject_nav(f.read(), depth=0, audio_date=dailies[0][0]))

    for iso, path in weeklies:
        with open(path, encoding="utf-8") as f:
            write(f"weekly/{iso}.html", inject_nav(f.read(), depth=1))
    for ym, path in monthlies:
        with open(path, encoding="utf-8") as f:
            write(f"monthly/{ym}.html", inject_nav(f.read(), depth=1))

    write("archive.html", build_index_page("Daily Archive",
        [(pretty_date(iso), f"reports/{iso}.html") for iso, _ in dailies],
        0, "No reports yet."))
    write("weekly/index.html", build_index_page("Weekly Overviews",
        [(f"Week of {pretty_date(iso)}", f"{iso}.html") for iso, _ in weeklies],
        1, "The first weekly overview arrives Monday morning."))
    write("monthly/index.html", build_index_page("Monthly Overviews",
        [(datetime.date.fromisoformat(ym + "-01").strftime("%B %Y"), f"{ym}.html") for ym, _ in monthlies],
        1, "The first monthly overview arrives on the 1st of next month."))

    print(f"Site built: {len(dailies)} daily, {len(weeklies)} weekly, {len(monthlies)} monthly")

if __name__ == "__main__":
    main()
