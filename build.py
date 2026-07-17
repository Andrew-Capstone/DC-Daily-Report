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
import os, re, glob, datetime, html

ROOT = os.path.dirname(os.path.abspath(__file__))


def nav_html(depth, active):
    """Render the nav bar with the current section highlighted.
    active is one of: 'today', 'daily', 'weekly', 'monthly'."""
    p = "../" * depth
    links = [
        ("today",   f"{p}index.html",         "Today"),
        ("daily",   f"{p}archive.html",        "Daily Archive"),
        ("weekly",  f"{p}weekly/index.html",   "Weekly"),
        ("monthly", f"{p}monthly/index.html",  "Monthly"),
    ]
    rows = []
    for key, href, label in links:
        style = ("color:#58a6ff;text-decoration:none;font-weight:600" if key == active
                 else "color:#8b949e;text-decoration:none")
        rows.append(f'  <a href="{href}" style="{style}">{label}</a>')
    return ('<nav style="max-width:860px;margin:0 auto 24px;display:flex;gap:18px;font-size:14px;\n'
            '  border-bottom:1px solid #2d333b;padding-bottom:12px;flex-wrap:wrap">\n'
            + "\n".join(rows) + "\n</nav>")

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


def summary_close_index(html_text):
    """Locate the TRUE closing </div> of the first <div class="summary"...> element.

    The summary body is LLM-generated, so it may one day contain nested <div>s.
    Rather than trust a non-greedy regex, find the opening tag then walk forward
    counting <div ...> openings against </div> closings until depth returns to 0.
    Returns the index at which the closing </div> starts, or None if not found.
    """
    m = re.search(r'<div\s+class="summary"', html_text)
    if not m:
        return None
    open_end = html_text.find(">", m.end())
    if open_end == -1:
        return None
    depth = 1
    for tok in re.finditer(r'<div\b|</div>', html_text[open_end + 1:]):
        if tok.group() == "</div>":
            depth -= 1
            if depth == 0:
                return open_end + 1 + tok.start()
        else:
            depth += 1
    return None


def discover_categories(html_text):
    """Discover filter categories from tag elements, order/whitespace-insensitive.

    Matches any element whose class attribute contains the token `tag`, pulls the
    `t-xxx` token out of the class list, and uses the element's inner text as the
    label. Returns a de-duplicated list of (t-class, label) in document order.
    """
    cats, seen = [], set()
    for m in re.finditer(r'class="([^"]*)"[^>]*>([^<]*)<', html_text):
        classes = m.group(1).split()
        if "tag" not in classes:
            continue
        tcls = next((c for c in classes if re.fullmatch(r"t-[a-z]+", c)), None)
        if not tcls:
            continue
        label = m.group(2).strip()
        if not label or label in seen:
            continue
        seen.add(label)
        cats.append((tcls, label))
    return cats


def inject_filters(html_text):
    """Add a category filter bar under the morning brief (.summary box).
    Categories are discovered from the tags actually present in the page."""
    cats = discover_categories(html_text)
    if not cats:
        return html_text
    buttons = '<button class="fbtn fbtn-all active" data-cat="all">All</button>'
    buttons += "".join(
        f'<button class="fbtn tag {cls}" data-cat="{html.escape(label)}">{html.escape(label)}</button>'
        for cls, label in cats)
    bar = f'<div id="catfilter"><span class="flabel">Filter:</span>{buttons}</div>'
    close = summary_close_index(html_text)
    if close is not None:
        after = close + len("</div>")
        out = html_text[:after] + "\n" + bar + html_text[after:]
    else:
        m = re.search(r"(</header>)", html_text)
        if not m:
            return html_text
        out = html_text[:m.end()] + "\n" + bar + html_text[m.end():]
    out = out.replace("</head>", FILTER_CSS + "\n</head>", 1)
    out = out.replace("</body>", FILTER_JS + "\n</body>", 1)
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
  a.addEventListener('error',function(){
    w.innerHTML='<span style="font-size:12.5px;color:#8b949e">Audio unavailable</span>';});
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
    close = summary_close_index(html_text)
    if close is None:
        return html_text
    out = html_text[:close] + player + html_text[close:]
    out = out.replace("</head>", PLAYER_CSS + "\n</head>", 1)
    out = out.replace("</body>", PLAYER_JS + "\n</body>", 1)
    return out


def add_noopener(html_text):
    """Every <a target="_blank"> without a rel= attribute gets rel="noopener"."""
    def repl(m):
        tag = m.group(0)
        if 'target="_blank"' in tag and not re.search(r"\brel=", tag):
            return tag[:-1] + ' rel="noopener">'
        return tag
    return re.sub(r"<a\b[^>]*>", repl, html_text)


def set_headline_count(html_text):
    """Rewrite the daily headline count to the number of story cards present."""
    n = html_text.count('class="card"')
    return re.sub(r"<h1>Top \d+ Stories</h1>", f"<h1>Top {n} Stories</h1>", html_text, count=1)


def inject_staleness_banner(html_text, date_iso):
    """index.html only: a hidden banner that JS reveals when the report is 2+ days old."""
    pretty = pretty_date(date_iso)
    banner = (
        '<div id="stalebanner" data-report-date="' + date_iso + '" '
        'style="display:none;background:#161b22;border:1px solid #2d333b;border-radius:8px;'
        'color:#d4a72c;font-size:13.5px;padding:10px 16px;margin-bottom:18px;max-width:860px;'
        'margin-left:auto;margin-right:auto">'
        'Latest report: ' + pretty + " — a newer report hasn't arrived yet.</div>"
    )
    script = (
        "<script>\n"
        "(function(){\n"
        "  var b=document.getElementById('stalebanner');\n"
        "  if(!b)return;\n"
        "  var p=b.getAttribute('data-report-date').split('-');\n"
        "  var rd=new Date(+p[0],+p[1]-1,+p[2]);\n"
        "  var n=new Date();\n"
        "  var t=new Date(n.getFullYear(),n.getMonth(),n.getDate());\n"
        "  var days=Math.round((t-rd)/86400000);\n"
        "  if(days>=2)b.style.display='';\n"
        "})();\n"
        "</script>"
    )
    out = re.sub(r"<header\b", lambda m: banner + "\n" + m.group(0), html_text, count=1)
    out = out.replace("</body>", script + "\n</body>", 1)
    return out


def inject_nav(html_text, depth, active, audio_date=None):
    nav = nav_html(depth, active)
    out = re.sub(r"(<body[^>]*>)", lambda m: m.group(1) + "\n" + nav, html_text, count=1)
    out = inject_filters(out)
    out = inject_audio_player(out, audio_date, depth)
    out = add_noopener(out)
    return out


def list_sources(subdir, pattern, is_month=False):
    d = os.path.join(ROOT, "source", subdir)
    if not os.path.isdir(d):
        return []
    out = []
    for f in sorted(os.listdir(d), reverse=True):
        m = re.match(pattern, f)
        if not m:
            continue
        key = m.group(1)
        try:
            datetime.date.fromisoformat(key + "-01" if is_month else key)
        except ValueError:
            print(f"Warning: skipping source/{subdir}/{f}: not a valid date ({key!r})")
            continue
        out.append((key, os.path.join(d, f)))
    return out


def prune_orphans(subdir, valid, pattern):
    """Delete generated pages (never index.html) with no matching source."""
    d = os.path.join(ROOT, subdir)
    if not os.path.isdir(d):
        return
    for f in sorted(os.listdir(d)):
        if f == "index.html":
            continue
        m = re.match(pattern, f)
        if not m:
            continue
        if m.group(1) not in valid:
            os.remove(os.path.join(d, f))
            print(f"Removed orphan {subdir}/{f}")


def prune_audio():
    """Delete audio/*.mp3 older than AUDIO_KEEP_DAYS (env, default 90) before today."""
    try:
        keep_days = int(os.environ.get("AUDIO_KEEP_DAYS", "90"))
    except ValueError:
        print("Warning: AUDIO_KEEP_DAYS is not an integer; falling back to 90")
        keep_days = 90
    cutoff = datetime.date.today() - datetime.timedelta(days=keep_days)
    audio_dir = os.path.join(ROOT, "audio")
    if not os.path.isdir(audio_dir):
        return
    for f in sorted(glob.glob(os.path.join(audio_dir, "*.mp3"))):
        m = re.match(r"^(\d{4}-\d{2}-\d{2})\.mp3$", os.path.basename(f))
        if not m:
            continue
        try:
            d = datetime.date.fromisoformat(m.group(1))
        except ValueError:
            continue
        if d < cutoff:
            os.remove(f)
            print("Pruned", os.path.basename(f))


def build_index_page(title, items, depth, empty_msg, active):
    if items:
        lis = "\n".join(f'<li><a href="{href}">{html.escape(label)}</a></li>' for label, href in items)
        body = f"<ul>{lis}</ul>"
    else:
        body = f'<p class="muted">{empty_msg}</p>'
    return PAGE_SHELL.format(title=title, nav=nav_html(depth, active), body=body)


def pretty_date(iso):
    return datetime.date.fromisoformat(iso).strftime("%A, %B %d, %Y").replace(" 0", " ")


def week_range_label(iso):
    """The weekly file date is the Monday of publication; the report covers the
    previous 7 days ending that Monday. Render as an inclusive range with a spaced
    en dash and no zero-padded day numbers."""
    end = datetime.date.fromisoformat(iso)
    start = end - datetime.timedelta(days=6)
    if start.year != end.year:
        return (f"{start.strftime('%B')} {start.day}, {start.year} – "
                f"{end.strftime('%B')} {end.day}, {end.year}")
    if start.month != end.month:
        return (f"{start.strftime('%B')} {start.day} – "
                f"{end.strftime('%B')} {end.day}, {end.year}")
    return f"{start.strftime('%B')} {start.day} – {end.day}, {end.year}"


def write(relpath, content):
    path = os.path.join(ROOT, relpath)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)


def main():
    prune_audio()

    dailies = list_sources("daily", r"^(\d{4}-\d{2}-\d{2})\.html$")
    weeklies = list_sources("weekly", r"^(\d{4}-\d{2}-\d{2})\.html$")
    monthlies = list_sources("monthly", r"^(\d{4}-\d{2})\.html$", is_month=True)

    # drop stale outputs whose source has been removed (never index.html)
    prune_orphans("reports", {iso for iso, _ in dailies}, r"^(\d{4}-\d{2}-\d{2})\.html$")
    prune_orphans("weekly", {iso for iso, _ in weeklies}, r"^(\d{4}-\d{2}-\d{2})\.html$")
    prune_orphans("monthly", {ym for ym, _ in monthlies}, r"^(\d{4}-\d{2})\.html$")

    for iso, path in dailies:
        try:
            with open(path, encoding="utf-8") as f:
                content = set_headline_count(f.read())
            write(f"reports/{iso}.html", inject_nav(content, depth=1, active="daily", audio_date=iso))
        except Exception as e:
            print(f"Warning: skipping {path}: {e}")
    if dailies:
        iso0, path0 = dailies[0]
        try:
            with open(path0, encoding="utf-8") as f:
                content = set_headline_count(f.read())
            page = inject_nav(content, depth=0, active="today", audio_date=iso0)
            page = inject_staleness_banner(page, iso0)
            write("index.html", page)
        except Exception as e:
            print(f"Warning: skipping index page from {path0}: {e}")

    for iso, path in weeklies:
        try:
            with open(path, encoding="utf-8") as f:
                write(f"weekly/{iso}.html", inject_nav(f.read(), depth=1, active="weekly"))
        except Exception as e:
            print(f"Warning: skipping {path}: {e}")
    for ym, path in monthlies:
        try:
            with open(path, encoding="utf-8") as f:
                write(f"monthly/{ym}.html", inject_nav(f.read(), depth=1, active="monthly"))
        except Exception as e:
            print(f"Warning: skipping {path}: {e}")

    write("archive.html", build_index_page("Daily Archive",
        [(pretty_date(iso), f"reports/{iso}.html") for iso, _ in dailies],
        0, "No reports yet.", "daily"))
    write("weekly/index.html", build_index_page("Weekly Overviews",
        [(week_range_label(iso), f"{iso}.html") for iso, _ in weeklies],
        1, "The first weekly overview arrives Monday morning.", "weekly"))
    write("monthly/index.html", build_index_page("Monthly Overviews",
        [(datetime.date.fromisoformat(ym + "-01").strftime("%B %Y"), f"{ym}.html") for ym, _ in monthlies],
        1, "The first monthly overview arrives on the first Monday of next month.", "monthly"))

    print(f"Site built: {len(dailies)} daily, {len(weeklies)} weekly, {len(monthlies)} monthly")


if __name__ == "__main__":
    main()
