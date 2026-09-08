import os
import json
import urllib.parse
import urllib.request
import urllib.error
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path
import base64
import binascii
import gzip
import io
import re
import tempfile


SERVER = os.environ["XTREAM_SERVER"].strip().rstrip("/")
USERNAME = os.environ["XTREAM_USERNAME"].strip()
PASSWORD = os.environ["XTREAM_PASSWORD"].strip()
CATEGORY_ID = "255"

# Public community EPG used only as a fallback.
EXTERNAL_EPG_URL = (
    "https://raw.githubusercontent.com/StrangeDrVN/epg/"
    "public/output/guide.xml.gz"
)


def fetch_bytes(url, timeout=90):
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 Malayalam-EPG-Updater"
        },
    )

    with urllib.request.urlopen(req, timeout=timeout) as response:
        return response.read()


def fetch_json(url, timeout=90):
    raw = fetch_bytes(url, timeout)
    return json.loads(
        raw.decode("utf-8", errors="replace")
    )


def api(action, **params):
    query = {
        "username": USERNAME,
        "password": PASSWORD,
        "action": action,
        **params,
    }

    url = (
        SERVER
        + "/player_api.php?"
        + urllib.parse.urlencode(query)
    )

    return fetch_json(url)


def decode_text(value):
    """
    Decode Base64 text used by some Xtream providers.
    Leave normal text unchanged.
    """

    if value is None:
        return ""

    text = str(value).strip()

    if not text:
        return ""

    if not re.fullmatch(
        r"[A-Za-z0-9+/=\s]+",
        text
    ):
        return text

    if len(text) < 8 or len(text) % 4 != 0:
        return text

    try:
        decoded = base64.b64decode(
            text,
            validate=True
        )

        decoded_text = decoded.decode("utf-8")

        printable = sum(
            1
            for c in decoded_text
            if c.isprintable()
            or c in "\n\r\t"
        )

        if (
            decoded_text
            and printable / len(decoded_text) > 0.90
        ):
            return decoded_text.strip()

    except (
        binascii.Error,
        UnicodeDecodeError,
        ValueError,
    ):
        pass

    return text


def parse_time(value):
    if value is None:
        return None

    if isinstance(value, (int, float)):
        try:
            return datetime.fromtimestamp(
                value,
                tz=timezone.utc
            )
        except Exception:
            return None

    text = str(value).strip()

    if not text:
        return None

    if text.isdigit():
        try:
            return datetime.fromtimestamp(
                int(text),
                tz=timezone.utc
            )
        except Exception:
            return None

    formats = [
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d %H:%M",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%dT%H:%M:%SZ",
        "%Y-%m-%dT%H:%M:%S.%fZ",
        "%Y%m%d%H%M%S +0000",
        "%Y%m%d%H%M%S +0000",
    ]

    for fmt in formats:
        try:
            dt = datetime.strptime(text, fmt)

            if dt.tzinfo is None:
                dt = dt.replace(
                    tzinfo=timezone.utc
                )

            return dt.astimezone(timezone.utc)

        except ValueError:
            pass

    return None


def xmltv_time(dt):
    return dt.strftime(
        "%Y%m%d%H%M%S +0000"
    )


def normalise_name(name):
    """
    Make channel names easier to compare between
    Strong8k and external EPG sources.
    """

    if not name:
        return ""

    text = decode_text(name).upper()

    text = re.sub(
        r"^(MALAYALAM|INDIA|INDIAN)\s*[:\-]\s*",
        "",
        text,
    )

    text = re.sub(
        r"\bHD\b",
        "",
        text,
    )

    text = re.sub(
        r"\bSD\b",
        "",
        text,
    )

    text = re.sub(
        r"[^A-Z0-9]+",
        "",
        text,
    )

    aliases = {
        "ZEEKERALAM": "ZEEKERALAM",
        "ZEEKERALAMHD": "ZEEKERALAM",
        "ASIANET": "ASIANET",
        "ASIANETHD": "ASIANET",
        "ASIANETNEWS": "ASIANETNEWS",
        "FLOWERS": "FLOWERS",
        "FLOWERSTV": "FLOWERS",
        "SURYA": "SURYATV",
        "SURYATV": "SURYATV",
        "SURYAMOVIES": "SURYAMOVIES",
        "SURYAMUSIC": "SURYAMUSIC",
        "KAIRALITV": "KAIRALI",
        "KAIRALI": "KAIRALI",
        "KAIRALINEWS": "KAIRALINEWS",
        "KAIRALIWE": "KAIRALIWE",
        "REPORTERTV": "REPORTER",
        "REPORTER": "REPORTER",
        "RAJMUSIXMALAYALAM": "RAJMUSIXMALAYALAM",
        "TWENTYFOUR": "TWENTYFOUR",
        "24NEWS": "TWENTYFOUR",
    }

    return aliases.get(
        text,
        text
    )


def get_provider_programmes(stream_id):
    """
    First fallback: Xtream short EPG.
    """

    try:
        result = api(
            "get_short_epg",
            stream_id=stream_id,
            limit=40,
        )

        if not isinstance(result, dict):
            return []

        listings = (
            result.get("epg_listings")
            or result.get("data")
            or []
        )

        if not isinstance(listings, list):
            return []

        return listings

    except Exception as exc:
        print(
            f"    Short EPG error: {exc}"
        )
        return []


def get_simple_provider_epg(stream_id):
    """
    Some Xtream servers expose EPG through
    get_simple_data_table instead.
    """

    try:
        result = api(
            "get_simple_data_table",
            stream_id=stream_id,
        )

        if isinstance(result, dict):
            listings = (
                result.get("epg_listings")
                or result.get("data")
                or result.get("epg")
                or []
            )

            if isinstance(listings, list):
                return listings

        if isinstance(result, list):
            return result

    except Exception as exc:
        print(
            f"    Simple EPG error: {exc}"
        )

    return []


def add_programmes(
    tv,
    channel_id,
    listings,
):
    count = 0

    for data in listings:

        if not isinstance(data, dict):
            continue

        start = parse_time(
            data.get("start")
            or data.get("start_time")
            or data.get("starttime")
        )

        stop = parse_time(
            data.get("end")
            or data.get("stop")
            or data.get("end_time")
            or data.get("endtime")
        )

        if (
            not start
            or not stop
            or stop <= start
        ):
            continue

        title = (
            data.get("title")
            or data.get("name")
            or data.get("program")
            or data.get("programme")
            or "Unknown programme"
        )

        title = decode_text(title)

        if not title:
            title = "Unknown programme"

        programme = ET.SubElement(
            tv,
            "programme",
            {
                "start": xmltv_time(start),
                "stop": xmltv_time(stop),
                "channel": channel_id,
            },
        )

        ET.SubElement(
            programme,
            "title"
        ).text = title

        description = (
            data.get("description")
            or data.get("desc")
            or data.get("plot")
        )

        if description:
            ET.SubElement(
                programme,
                "desc"
            ).text = decode_text(
                description
            )

        category = data.get("category")

        if category:
            ET.SubElement(
                programme,
                "category"
            ).text = decode_text(
                category
            )

        count += 1

    return count


def download_external_epg():
    """
    Download the public community guide.
    """

    print("")
    print(
        "Downloading external fallback EPG..."
    )

    try:
        raw = fetch_bytes(
            EXTERNAL_EPG_URL,
            timeout=120,
        )

        if raw[:2] == b"\x1f\x8b":
            raw = gzip.decompress(raw)

        print(
            f"External EPG downloaded: "
            f"{len(raw):,} bytes"
        )

        return raw

    except Exception as exc:
        print(
            f"External EPG unavailable: {exc}"
        )
        return None


def parse_external_epg(raw):
    """
    Parse external XMLTV into:

        normalised channel name -> programmes

    Only unique channel-name matches are accepted.
    """

    if not raw:
        return {}

    source = io.BytesIO(raw)

    try:
        root = ET.parse(source).getroot()
    except ET.ParseError as exc:
        print(
            f"External EPG XML error: {exc}"
        )
        return {}

    channels = {}

    for channel in root.findall("channel"):

        channel_id = (
            channel.get("id")
            or ""
        )

        names = []

        for display in channel.findall(
            "display-name"
        ):
            if display.text:
                names.append(
                    display.text.strip()
                )

        if not names:
            continue

        normalised = normalise_name(
            names[0]
        )

        if not normalised:
            continue

        channels.setdefault(
            normalised,
            []
        ).append(channel_id)

    # Only keep names which map to one source
    # channel. This avoids accidental matches.
    unique_channels = {
        name: ids[0]
        for name, ids in channels.items()
        if len(ids) == 1
    }

    programmes = {}

    for programme in root.findall(
        "programme"
    ):

        source_id = (
            programme.get("channel")
            or ""
        )

        source_name = None

        for name, candidate_id in (
            unique_channels.items()
        ):
            if candidate_id == source_id:
                source_name = name
                break

        if not source_name:
            continue

        start = parse_time(
            programme.get("start")
        )

        stop = parse_time(
            programme.get("stop")
        )

        if (
            not start
            or not stop
            or stop <= start
        ):
            continue

        title_node = programme.find("title")

        title = (
            title_node.text
            if title_node is not None
            else ""
        )

        title = decode_text(title)

        if not title:
            continue

        item = {
            "start": start,
            "stop": stop,
            "title": title,
        }

        desc_node = programme.find("desc")

        if (
            desc_node is not None
            and desc_node.text
        ):
            item["description"] = (
                decode_text(
                    desc_node.text
                )
            )

        programmes.setdefault(
            source_name,
            []
        ).append(item)

    return programmes


def add_external_programmes(
    tv,
    channel_id,
    listings,
):
    count = 0

    for data in listings:

        programme = ET.SubElement(
            tv,
            "programme",
            {
                "start": xmltv_time(
                    data["start"]
                ),
                "stop": xmltv_time(
                    data["stop"]
                ),
                "channel": channel_id,
            },
        )

        ET.SubElement(
            programme,
            "title"
        ).text = data["title"]

        if data.get("description"):
            ET.SubElement(
                programme,
                "desc"
            ).text = data[
                "description"
            ]

        count += 1

    return count


# ---------------------------------------------------------
# 1. Get category 255 channels
# ---------------------------------------------------------

streams = api(
    "get_live_streams",
    category_id=CATEGORY_ID,
)

if not isinstance(streams, list):
    raise RuntimeError(
        "get_live_streams did not return a channel list."
    )

streams = [
    s
    for s in streams
    if str(s.get("category_id"))
    == CATEGORY_ID
    and s.get("stream_id") is not None
]

if not streams:
    raise RuntimeError(
        "No channels found in category 255."
    )

print(
    f"Found {len(streams)} category-255 channels."
)


# ---------------------------------------------------------
# 2. Download external fallback before building XML
# ---------------------------------------------------------

external_raw = download_external_epg()

external_programmes = {}

if external_raw:
    external_programmes = parse_external_epg(
        external_raw
    )

print(
    f"External channel matches available: "
    f"{len(external_programmes)}"
)


# ---------------------------------------------------------
# 3. Build XMLTV
# ---------------------------------------------------------

tv = ET.Element(
    "tv",
    {
        "generator-info-name":
            "GitHub Malayalam Hybrid EPG updater"
    },
)

provider_channels = 0
external_channels = 0
programme_count = 0


for index, stream in enumerate(
    streams,
    start=1,
):

    stream_id = str(
        stream["stream_id"]
    )

    channel_name = str(
        stream.get("name")
        or f"Stream {stream_id}"
    ).strip()

    provider_epg_id = str(
        stream.get("epg_channel_id")
        or ""
    ).strip()

    logo = str(
        stream.get("stream_icon")
        or ""
    ).strip()

    channel_id = (
        provider_epg_id
        if provider_epg_id
        else f"malayalam-{stream_id}"
    )

    print("")
    print(
        f"[{index}/{len(streams)}] "
        f"{channel_name} "
        f"({stream_id})"
    )

    channel = ET.SubElement(
        tv,
        "channel",
        {"id": channel_id},
    )

    ET.SubElement(
        channel,
        "display-name",
    ).text = channel_name

    if logo:
        ET.SubElement(
            channel,
            "icon",
            {"src": logo},
        )

    # -----------------------------------------------------
    # Provider EPG
    # -----------------------------------------------------

    listings = get_provider_programmes(
        stream_id
    )

    added = add_programmes(
        tv,
        channel_id,
        listings,
    )

    # Try simple_data_table if short EPG
    # produced nothing.
    if added == 0:
        simple = get_simple_provider_epg(
            stream_id
        )

        if simple:
            added = add_programmes(
                tv,
                channel_id,
                simple,
            )

    if added:
        provider_channels += 1
        programme_count += added

        print(
            f"  Strong8k EPG: "
            f"{added} programmes"
        )

        # Strong8k data wins.
        continue

    # -----------------------------------------------------
    # External fallback
    # -----------------------------------------------------

    key = normalise_name(
        channel_name
    )

    external = (
        external_programmes.get(key)
        or []
    )

    if external:

        added_external = add_external_programmes(
            tv,
            channel_id,
            external,
        )

        if added_external:
            external_channels += 1
            programme_count += (
                added_external
            )

            print(
                f"  External EPG: "
                f"{added_external} programmes"
            )

            continue

    print(
        "  No EPG found."
    )


# ---------------------------------------------------------
# 4. Sort programmes by channel/start time
# ---------------------------------------------------------

programmes = list(
    tv.findall("programme")
)

for programme in programmes:
    tv.remove(programme)

programmes.sort(
    key=lambda p: (
        p.get("channel", ""),
        p.get("start", ""),
    )
)

for programme in programmes:
    tv.append(programme)


# ---------------------------------------------------------
# 5. Write XMLTV
# ---------------------------------------------------------

ET.indent(
    tv,
    space="  "
)

ET.ElementTree(tv).write(
    "malayalam.xml",
    encoding="utf-8",
    xml_declaration=True,
)


print("")
print("=" * 50)
print(
    f"Channels found: {len(streams)}"
)
print(
    f"Channels using Strong8k EPG: "
    f"{provider_channels}"
)
print(
    f"Channels using external EPG: "
    f"{external_channels}"
)
print(
    f"Total programmes written: "
    f"{programme_count}"
)
print("=" * 50)


if programme_count == 0:
    raise RuntimeError(
        "No usable EPG data was found."
    )
