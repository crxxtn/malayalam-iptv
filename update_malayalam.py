import os
import json
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path

SERVER = os.environ["XTREAM_SERVER"].rstrip("/")
USERNAME = os.environ["XTREAM_USERNAME"]
PASSWORD = os.environ["XTREAM_PASSWORD"]
CATEGORY_ID = "255"

def get_json(url):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read().decode("utf-8", errors="replace"))

def get_bytes(url):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=120) as r:
        return r.read()

def api(action, **params):
    q = {
        "username": USERNAME,
        "password": PASSWORD,
        "action": action,
        **params,
    }
    return get_json(SERVER + "/player_api.php?" + urllib.parse.urlencode(q))

# Fetch current category 255 channels directly from the provider.
streams = api("get_live_streams", category_id=CATEGORY_ID)
if not isinstance(streams, list):
    raise RuntimeError(f"Unexpected get_live_streams response: {streams!r}")

streams = [s for s in streams if str(s.get("category_id")) == CATEGORY_ID]
if not streams:
    raise RuntimeError("No category 255 channels were returned.")

# Build M3U using the provider's EPG channel id where available.
m3u = ["#EXTM3U"]
for s in streams:
    name = s.get("name", f"Stream {s.get('stream_id')}")
    sid = s["stream_id"]
    epg_id = s.get("epg_channel_id") or ""
    logo = s.get("stream_icon") or ""
    group = "ASIA | MALAYALAM"

    attrs = [
        f'tvg-id="{epg_id}"' if epg_id else "",
        f'tvg-name="{name}"',
        f'tvg-logo="{logo}"' if logo else "",
        f'group-title="{group}"',
    ]
    attrs = " ".join(x for x in attrs if x)

    # Xtream live-stream URL.
    url = (
        SERVER + "/live/" +
        urllib.parse.quote(USERNAME, safe="") + "/" +
        urllib.parse.quote(PASSWORD, safe="") + "/" +
        str(sid) + ".ts"
    )
    m3u.append(f"#EXTINF:-1 {attrs},{name}")
    m3u.append(url)

Path("malayalam.m3u").write_text("\n".join(m3u) + "\n", encoding="utf-8")

# Fetch provider XMLTV and keep only the channels used by category 255.
xml_bytes = get_bytes(
    SERVER + "/xmltv.php?" + urllib.parse.urlencode({
        "username": USERNAME,
        "password": PASSWORD,
        "prev_days": 1,
        "next_days": 3,
    })
)

root = ET.fromstring(xml_bytes)

wanted = {
    str(s.get("epg_channel_id"))
    for s in streams
    if s.get("epg_channel_id")
}

# If the provider's XMLTV has no matching IDs, fall back to per-stream short EPG.
available_ids = {c.get("id") for c in root.findall("channel")}
matched = wanted & available_ids

if not matched:
    out = ET.Element("tv", {
        "generator-info-name": "GitHub Malayalam Xtream EPG updater"
    })

    for s in streams:
        epg_id = s.get("epg_channel_id") or f"stream-{s['stream_id']}"
        ch = ET.SubElement(out, "channel", {"id": epg_id})
        ET.SubElement(ch, "display-name").text = s.get("name", epg_id)
        if s.get("stream_icon"):
            ET.SubElement(ch, "icon", {"src": s["stream_icon"]})

        try:
            data = api(
                "get_short_epg",
                stream_id=s["stream_id"],
                limit=20,
            )
            for p in data.get("epg_listings", []):
                start = p.get("start")
                end = p.get("end")
                if not start or not end:
                    continue
                try:
                    st = datetime.strptime(start, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
                    en = datetime.strptime(end, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
                    start_xml = st.strftime("%Y%m%d%H%M%S %z").replace("+0000", "+0000")
                    end_xml = en.strftime("%Y%m%d%H%M%S %z").replace("+0000", "+0000")
                except ValueError:
                    continue

                prog = ET.SubElement(out, "programme", {
                    "start": start_xml,
                    "stop": end_xml,
                    "channel": epg_id,
                })
                ET.SubElement(prog, "title").text = p.get("title", "")
                if p.get("description"):
                    ET.SubElement(prog, "desc").text = p["description"]
        except Exception as exc:
            print(f"EPG failed for {s['stream_id']}: {exc}")

    root = out
else:
    # Remove channels/programmes that are not category 255.
    for ch in list(root.findall("channel")):
        if ch.get("id") not in matched:
            root.remove(ch)
    for prog in list(root.findall("programme")):
        if prog.get("channel") not in matched:
            root.remove(prog)

ET.ElementTree(root).write("malayalam.xml", encoding="utf-8", xml_declaration=True)

print(f"Updated {len(streams)} Malayalam channels.")
print(f"Matched {len(matched)} channels from provider XMLTV.")
