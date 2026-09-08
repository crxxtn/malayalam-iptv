import os
import json
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path
import html
import re

SERVER = os.environ["XTREAM_SERVER"].strip().rstrip("/")
USERNAME = os.environ["XTREAM_USERNAME"].strip()
PASSWORD = os.environ["XTREAM_PASSWORD"].strip()
CATEGORY_ID = "255"

def fetch_json(url, timeout=60):
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "Mozilla/5.0"}
    )
    with urllib.request.urlopen(req, timeout=timeout) as response:
        raw = response.read()
    return json.loads(raw.decode("utf-8", errors="replace"))

def api(action, **params):
    query = {
        "username": USERNAME,
        "password": PASSWORD,
        "action": action,
        **params,
    }
    url = SERVER + "/player_api.php?" + urllib.parse.urlencode(query)
    return fetch_json(url)

def xml_escape(value):
    if value is None:
        return ""
    return html.escape(str(value), quote=False)

def parse_time(value):
    """Return UTC datetime from common Xtream EPG formats."""
    if value is None:
        return None

    # Unix timestamp
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(value, tz=timezone.utc)

    text = str(value).strip()
    if not text:
        return None

    if text.isdigit():
        return datetime.fromtimestamp(int(text), tz=timezone.utc)

    formats = [
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d %H:%M",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%dT%H:%M:%SZ",
    ]

    for fmt in formats:
        try:
            dt = datetime.strptime(text, fmt)
            return dt.replace(tzinfo=timezone.utc)
        except ValueError:
            pass

    return None

def xmltv_time(dt):
    return dt.strftime("%Y%m%d%H%M%S +0000")

# 1. Get the current category 255 channels.
streams = api("get_live_streams", category_id=CATEGORY_ID)

if not isinstance(streams, list):
    raise RuntimeError("get_live_streams did not return a channel list.")

streams = [
    s for s in streams
    if str(s.get("category_id")) == CATEGORY_ID and s.get("stream_id") is not None
]

if not streams:
    raise RuntimeError("No channels found in category 255.")

print(f"Found {len(streams)} category-255 channels.")

# 2. Build the M3U.
m3u = ["#EXTM3U"]

for s in streams:
    name = str(s.get("name") or f"Stream {s['stream_id']}")
    sid = str(s["stream_id"])
    epg_id = str(s.get("epg_channel_id") or "")
    logo = str(s.get("stream_icon") or "")
    group = "ASIA | MALAYALAM"

    attrs = [
        f'tvg-id="{epg_id}"' if epg_id else "",
        f'tvg-name="{name}"',
        f'tvg-logo="{logo}"' if logo else "",
        f'group-title="{group}"',
    ]
    attrs = " ".join(x for x in attrs if x)

    url = (
        SERVER + "/live/" +
        urllib.parse.quote(USERNAME, safe="") + "/" +
        urllib.parse.quote(PASSWORD, safe="") + "/" +
        sid + ".ts"
    )

    m3u.append(f"#EXTINF:-1 {attrs},{name}")
    m3u.append(url)

Path("malayalam.m3u").write_text(
    "\n".join(m3u) + "\n",
    encoding="utf-8"
)

# 3. Build XMLTV from each channel's own EPG.
tv = ET.Element("tv", {
    "generator-info-name": "GitHub Malayalam Xtream EPG updater"
})

success = 0
programme_count = 0

for index, s in enumerate(streams, start=1):
    sid = str(s["stream_id"])
    name = str(s.get("name") or f"Stream {sid}")
    epg_id = str(s.get("epg_channel_id") or f"stream-{sid}")
    logo = str(s.get("stream_icon") or "")

    channel = ET.SubElement(tv, "channel", {"id": epg_id})
    ET.SubElement(channel, "display-name").text = name

    if logo:
        ET.SubElement(channel, "icon", {"src": logo})

    print(f"[{index}/{len(streams)}] Getting EPG for {name} ({sid})")

    try:
        result = api("get_short_epg", stream_id=sid, limit=40)

        if not isinstance(result, dict):
            print("  No usable EPG response.")
            continue

        listings = result.get("epg_listings") or []

        # Some providers use a direct list.
        if not listings and isinstance(result.get("data"), list):
            listings = result["data"]

        added_here = 0

        for p in listings:
            start = parse_time(p.get("start"))
            stop = parse_time(p.get("end"))

            if not start or not stop or stop <= start:
                continue

            programme = ET.SubElement(
                tv,
                "programme",
                {
                    "start": xmltv_time(start),
                    "stop": xmltv_time(stop),
                    "channel": epg_id,
                },
            )

            title = (
                p.get("title")
                or p.get("name")
                or p.get("program")
                or "Unknown programme"
            )
            ET.SubElement(programme, "title").text = str(title)

            description = (
                p.get("description")
                or p.get("desc")
                or p.get("plot")
            )
            if description:
                ET.SubElement(programme, "desc").text = str(description)

            category = p.get("category")
            if category:
                ET.SubElement(programme, "category").text = str(category)

            added_here += 1

        if added_here:
            success += 1
            programme_count += added_here
            print(f"  Added {added_here} programmes.")
        else:
            print("  No programmes returned.")

    except Exception as exc:
        print(f"  EPG error: {exc}")

# 4. Write XMLTV.
ET.indent(tv, space="  ")
ET.ElementTree(tv).write(
    "malayalam.xml",
    encoding="utf-8",
    xml_declaration=True
)

print("")
print(f"Finished. Channels: {len(streams)}")
print(f"Channels with EPG data: {success}")
print(f"Programmes written: {programme_count}")

if success == 0:
    raise RuntimeError(
        "The provider returned no usable EPG data for any category-255 channel."
    )
