import os
import json
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path
import html
import base64
import binascii
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


def decode_text(value):
    """
    Xtream providers commonly return EPG titles/descriptions
    as Base64. Decode them when appropriate, otherwise leave
    the original text unchanged.
    """

    if value is None:
        return ""

    text = str(value).strip()

    if not text:
        return ""

    # Already looks like normal readable text
    if not re.fullmatch(r"[A-Za-z0-9+/=\s]+", text):
        return text

    # Base64 normally has a length divisible by 4
    if len(text) < 8 or len(text) % 4 != 0:
        return text

    try:
        decoded = base64.b64decode(text, validate=True)

        decoded_text = decoded.decode("utf-8")

        # Only use the decoded version if it is mostly printable
        printable = sum(
            1 for c in decoded_text
            if c.isprintable() or c in "\n\r\t"
        )

        if len(decoded_text) > 0 and printable / len(decoded_text) > 0.90:
            return decoded_text.strip()

    except (binascii.Error, UnicodeDecodeError, ValueError):
        pass

    return text


def parse_time(value):
    """
    Convert common Xtream EPG date formats into UTC datetime.
    """

    if value is None:
        return None

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
        "%Y-%m-%dT%H:%M:%S.%fZ",
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


# ---------------------------------------------------------
# 1. Get current category 255 channels
# ---------------------------------------------------------

streams = api(
    "get_live_streams",
    category_id=CATEGORY_ID
)

if not isinstance(streams, list):
    raise RuntimeError(
        "get_live_streams did not return a channel list."
    )


streams = [
    s for s in streams
    if str(s.get("category_id")) == CATEGORY_ID
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
# 2. Build XMLTV
# ---------------------------------------------------------

tv = ET.Element(
    "tv",
    {
        "generator-info-name":
            "GitHub Malayalam Xtream EPG updater"
    }
)


success = 0
programme_count = 0


for index, stream in enumerate(streams, start=1):

    stream_id = str(stream["stream_id"])

    channel_name = str(
        stream.get("name")
        or f"Stream {stream_id}"
    ).strip()

    provider_epg_id = str(
        stream.get("epg_channel_id") or ""
    ).strip()

    logo = str(
        stream.get("stream_icon") or ""
    ).strip()


    # Use provider EPG ID when available.
    # Otherwise use a stable ID based on the stream ID.
    channel_id = (
        provider_epg_id
        if provider_epg_id
        else f"malayalam-{stream_id}"
    )


    print(
        f"[{index}/{len(streams)}] "
        f"Getting EPG for {channel_name} "
        f"({stream_id})"
    )


    # Create channel
    channel = ET.SubElement(
        tv,
        "channel",
        {"id": channel_id}
    )

    ET.SubElement(
        channel,
        "display-name"
    ).text = channel_name


    if logo:
        ET.SubElement(
            channel,
            "icon",
            {"src": logo}
        )


    try:

        result = api(
            "get_short_epg",
            stream_id=stream_id,
            limit=40
        )


        if not isinstance(result, dict):
            print("  No usable EPG response.")
            continue


        listings = result.get(
            "epg_listings"
        ) or []


        # Some Xtream providers use "data"
        if (
            not listings
            and isinstance(result.get("data"), list)
        ):
            listings = result["data"]


        added_here = 0


        for programme_data in listings:

            start = parse_time(
                programme_data.get("start")
            )

            stop = parse_time(
                programme_data.get("end")
            )


            if (
                not start
                or not stop
                or stop <= start
            ):
                continue


            programme = ET.SubElement(
                tv,
                "programme",
                {
                    "start": xmltv_time(start),
                    "stop": xmltv_time(stop),
                    "channel": channel_id,
                },
            )


            # Decode Base64 programme title
            title = (
                programme_data.get("title")
                or programme_data.get("name")
                or programme_data.get("program")
                or "Unknown programme"
            )

            title = decode_text(title)


            ET.SubElement(
                programme,
                "title"
            ).text = title


            # Decode description if present
            description = (
                programme_data.get("description")
                or programme_data.get("desc")
                or programme_data.get("plot")
            )


            if description:
                description = decode_text(
                    description
                )

                ET.SubElement(
                    programme,
                    "desc"
                ).text = description


            category = programme_data.get(
                "category"
            )


            if category:
                category = decode_text(
                    category
                )

                ET.SubElement(
                    programme,
                    "category"
                ).text = category


            added_here += 1


        if added_here:

            success += 1
            programme_count += added_here

            print(
                f"  Added {added_here} programmes."
            )

        else:
            print(
                "  No programmes returned."
            )


    except Exception as exc:

        print(
            f"  EPG error: {exc}"
        )


# ---------------------------------------------------------
# 3. Write XMLTV
# ---------------------------------------------------------

ET.indent(
    tv,
    space="  "
)


ET.ElementTree(tv).write(
    "malayalam.xml",
    encoding="utf-8",
    xml_declaration=True
)


print("")
print(
    f"Finished. Channels: {len(streams)}"
)
print(
    f"Channels with EPG data: {success}"
)
print(
    f"Programmes written: {programme_count}"
)


if success == 0:
    raise RuntimeError(
        "The provider returned no usable EPG "
        "data for any category-255 channel."
    )
