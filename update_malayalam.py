import os
import re
import gzip
import urllib.request
import urllib.parse
import xml.etree.ElementTree as ET
from collections import defaultdict
from datetime import datetime, timezone


SERVER = os.environ["XTREAM_SERVER"].rstrip("/")
USERNAME = os.environ["XTREAM_USERNAME"].strip()
PASSWORD = os.environ["XTREAM_PASSWORD"].strip()

CATEGORY_ID = "255"

FULL_XMLTV_URL = (
    f"{SERVER}/xmltv.php?"
    f"username={urllib.parse.quote(USERNAME)}&"
    f"password={urllib.parse.quote(PASSWORD)}&"
    f"prev_days=0&next_days=3"
)

SHORT_EPG_LIMIT = 40

OUTPUT_FILE = "malayalam.xml"


def decode_base64(value):
    if not value:
        return ""

    try:
        import base64

        value = value.strip()

        # Xtream sometimes returns Base64 without padding
        value += "=" * (-len(value) % 4)

        decoded = base64.b64decode(value).decode("utf-8", errors="ignore")
        return decoded.strip()
    except Exception:
        return value


def clean_text(value):
    if value is None:
        return ""

    value = str(value)
    value = re.sub(r"\s+", " ", value)
    return value.strip()


def request_json(url):
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 Malayalam-EPG-Updater"
        },
    )

    with urllib.request.urlopen(req, timeout=60) as response:
        data = response.read()

    import json
    return json.loads(data.decode("utf-8", errors="ignore"))


def get_malayalam_channels():
    url = (
        f"{SERVER}/player_api.php?"
        f"username={urllib.parse.quote(USERNAME)}&"
        f"password={urllib.parse.quote(PASSWORD)}&"
        f"action=get_live_streams&"
        f"category_id={CATEGORY_ID}"
    )

    data = request_json(url)

    channels = []

    for item in data:
        stream_id = str(item.get("stream_id", "")).strip()

        if not stream_id:
            continue

        channels.append(
            {
                "stream_id": stream_id,
                "name": clean_text(item.get("name", "")),
                "epg_id": clean_text(item.get("epg_channel_id", "")),
                "logo": clean_text(item.get("stream_icon", "")),
            }
        )

    return channels


def get_short_epg(stream_id):
    url = (
        f"{SERVER}/player_api.php?"
        f"username={urllib.parse.quote(USERNAME)}&"
        f"password={urllib.parse.quote(PASSWORD)}&"
        f"action=get_short_epg&"
        f"stream_id={urllib.parse.quote(stream_id)}&"
        f"limit={SHORT_EPG_LIMIT}"
    )

    try:
        data = request_json(url)

        listings = data.get("epg_listings", [])

        programmes = []

        for item in listings:
            start = item.get("start", "")
            stop = item.get("end", "")

            title = decode_base64(item.get("title", ""))
            description = decode_base64(item.get("description", ""))

            if not start or not stop or not title:
                continue

            programmes.append(
                {
                    "start": start,
                    "stop": stop,
                    "title": title,
                    "description": description,
                }
            )

        return programmes

    except Exception as e:
        print(f"Short EPG failed for {stream_id}: {e}")
        return []


def parse_full_xmltv():
    """
    Download Strong8k's full XMLTV feed and extract only programmes
    belonging to the Malayalam provider EPG IDs.

    The feed can occasionally be truncated by the server. We therefore
    use iterparse so programmes already read can still be retained.
    """

    wanted_ids = {
        channel["epg_id"]
        for channel in CHANNELS
        if channel["epg_id"]
    }

    print(f"Provider EPG IDs to search for: {len(wanted_ids)}")

    programmes = defaultdict(list)

    req = urllib.request.Request(
        FULL_XMLTV_URL,
        headers={
            "User-Agent": "Mozilla/5.0 Malayalam-EPG-Updater"
        },
    )

    temp_file = "strong8k.xml"

    print("Downloading Strong8k full XMLTV...")

    try:
        with urllib.request.urlopen(req, timeout=180) as response:
            with open(temp_file, "wb") as f:
                while True:
                    chunk = response.read(1024 * 1024)

                    if not chunk:
                        break

                    f.write(chunk)

    except Exception as e:
        print(f"Full XMLTV download failed: {e}")
        return programmes

    print("Parsing Strong8k XMLTV...")

    parsed = 0

    try:
        context = ET.iterparse(
            temp_file,
            events=("end",)
        )

        for event, elem in context:

            if elem.tag != "programme":
                continue

            channel_id = elem.attrib.get("channel", "").strip()

            if channel_id not in wanted_ids:
                elem.clear()
                continue

            start = elem.attrib.get("start", "").strip()
            stop = elem.attrib.get("stop", "").strip()

            title_element = elem.find("title")
            desc_element = elem.find("desc")

            title = ""
            description = ""

            if title_element is not None:
                title = clean_text(title_element.text)

            if desc_element is not None:
                description = clean_text(desc_element.text)

            if start and stop and title:
                programmes[channel_id].append(
                    {
                        "start": start,
                        "stop": stop,
                        "title": title,
                        "description": description,
                    }
                )

                parsed += 1

            elem.clear()

    except ET.ParseError as e:
        print(f"XMLTV ended unexpectedly: {e}")
        print("Keeping programmes successfully parsed before the error.")

    except Exception as e:
        print(f"XMLTV parsing error: {e}")

    print(f"Full XMLTV programmes found: {parsed}")

    return programmes


def normalise_epg_id(value):
    value = clean_text(value)

    if not value:
        return ""

    return value.strip()


def xml_escape(value):
    if value is None:
        return ""

    return (
        str(value)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&apos;")
    )


def make_channel_id(channel):
    """
    Preserve the provider's EPG ID whenever possible.

    This is important because TiviMate matches the playlist tvg-id
    against the XMLTV channel id.
    """

    epg_id = normalise_epg_id(channel["epg_id"])

    if epg_id:
        return epg_id

    return f"malayalam-{channel['stream_id']}"


def add_programmes(
    programme_store,
    channel_id,
    programmes,
):
    existing = programme_store[channel_id]

    seen = {
        (
            p["start"],
            p["stop"],
            p["title"],
        )
        for p in existing
    }

    for programme in programmes:
        key = (
            programme["start"],
            programme["stop"],
            programme["title"],
        )

        if key not in seen:
            existing.append(programme)
            seen.add(key)


def build_epg():
    global CHANNELS

    CHANNELS = get_malayalam_channels()

    print(f"Malayalam channels: {len(CHANNELS)}")

    strong8k_channels = [
        channel for channel in CHANNELS
        if channel["epg_id"]
    ]

    print(
        f"Strong8k channels with EPG: "
        f"{len(strong8k_channels)}"
    )

    full_epg = parse_full_xmltv()

    programme_store = defaultdict(list)

    # ---------------------------------------------------------
    # 1. FULL XMLTV
    # ---------------------------------------------------------

    full_matches = 0

    for channel in CHANNELS:
        epg_id = channel["epg_id"]

        if not epg_id:
            continue

        programmes = full_epg.get(epg_id, [])

        if programmes:
            channel_id = make_channel_id(channel)

            add_programmes(
                programme_store,
                channel_id,
                programmes,
            )

            full_matches += 1

    print(
        f"Full XMLTV channels with programmes: "
        f"{full_matches}"
    )

    # ---------------------------------------------------------
    # 2. SHORT EPG FALLBACK
    # ---------------------------------------------------------

    fallback_channels = 0

    for channel in CHANNELS:
        channel_id = make_channel_id(channel)

        if programme_store[channel_id]:
            continue

        programmes = get_short_epg(
            channel["stream_id"]
        )

        if programmes:
            add_programmes(
                programme_store,
                channel_id,
                programmes,
            )

            fallback_channels += 1

    print(
        f"Short EPG fallback channels: "
        f"{fallback_channels}"
    )

    # ---------------------------------------------------------
    # BUILD XMLTV
    # ---------------------------------------------------------

    lines = []

    lines.append(
        '<?xml version="1.0" encoding="UTF-8"?>'
    )

    lines.append(
        '<tv generator-info-name="Malayalam Strong8k EPG updater">'
    )

    # Channels
    for channel in CHANNELS:

        channel_id = make_channel_id(channel)

        lines.append(
            f'  <channel id="{xml_escape(channel_id)}">'
        )

        lines.append(
            f'    <display-name>'
            f'{xml_escape(channel["name"])}'
            f'</display-name>'
        )

        if channel["logo"]:
            lines.append(
                f'    <icon src="{xml_escape(channel["logo"])}"/>'
            )

        lines.append(
            "  </channel>"
        )

    # Programmes
    total_programmes = 0

    for channel in CHANNELS:

        channel_id = make_channel_id(channel)

        programmes = programme_store.get(
            channel_id,
            []
        )

        # Sort chronologically
        programmes.sort(
            key=lambda p: p["start"]
        )

        for programme in programmes:

            lines.append(
                f'  <programme '
                f'start="{xml_escape(programme["start"])}" '
                f'stop="{xml_escape(programme["stop"])}" '
                f'channel="{xml_escape(channel_id)}">'
            )

            lines.append(
                f'    <title>{xml_escape(programme["title"])}</title>'
            )

            if programme["description"]:
                lines.append(
                    f'    <desc>'
                    f'{xml_escape(programme["description"])}'
                    f'</desc>'
                )

            lines.append(
                "  </programme>"
            )

            total_programmes += 1

    lines.append("</tv>")

    with open(
        OUTPUT_FILE,
        "w",
        encoding="utf-8"
    ) as f:

        f.write(
            "\n".join(lines)
        )

    print()
    print("======================================")
    print("Malayalam EPG generation complete")
    print("======================================")
    print(f"Malayalam channels: {len(CHANNELS)}")
    print(
        f"Strong8k channels with EPG: "
        f"{len(strong8k_channels)}"
    )
    print(
        f"Full XMLTV channels with programmes: "
        f"{full_matches}"
    )
    print(
        f"Short EPG fallback channels: "
        f"{fallback_channels}"
    )
    print(
        f"Total programmes: "
        f"{total_programmes}"
    )
    print("======================================")


if __name__ == "__main__":
    build_epg()
