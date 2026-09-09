import os
import json
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
import base64
import binascii
import gzip
import io
import re


SERVER = os.environ["XTREAM_SERVER"].strip().rstrip("/")
USERNAME = os.environ["XTREAM_USERNAME"].strip()
PASSWORD = os.environ["XTREAM_PASSWORD"].strip()

CATEGORY_ID = "255"

EXTERNAL_EPG_URL = (
    "https://iptv-org.github.io/epg/guides/en/dishtv.in.xml"
)


def fetch_bytes(url, timeout=120):
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 Malayalam-EPG"
        },
    )

    with urllib.request.urlopen(
        request,
        timeout=timeout
    ) as response:
        return response.read()


def fetch_json(url, timeout=90):
    raw = fetch_bytes(url, timeout)

    return json.loads(
        raw.decode(
            "utf-8",
            errors="replace"
        )
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

    if len(text) < 8:
        return text

    if len(text) % 4 != 0:
        return text

    try:

        decoded = base64.b64decode(
            text,
            validate=True
        )

        decoded_text = decoded.decode(
            "utf-8"
        )

        printable = sum(
            1
            for char in decoded_text
            if char.isprintable()
            or char in "\n\r\t"
        )

        if (
            decoded_text
            and printable / len(decoded_text)
            > 0.90
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

    if isinstance(
        value,
        (int, float)
    ):
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

            dt = datetime.strptime(
                text,
                fmt
            )

            if dt.tzinfo is None:
                dt = dt.replace(
                    tzinfo=timezone.utc
                )

            return dt.astimezone(
                timezone.utc
            )

        except ValueError:
            pass

    return None


def xmltv_time(dt):

    return dt.strftime(
        "%Y%m%d%H%M%S +0000"
    )


def clean_name(name):

    if not name:
        return ""

    text = decode_text(
        name
    ).upper()

    text = text.replace(
        "&",
        "AND"
    )

    text = re.sub(
        r"^MALAYALAM\s*[:\-]\s*",
        "",
        text
    )

    text = re.sub(
        r"\bHD\b",
        "",
        text
    )

    text = re.sub(
        r"\bSD\b",
        "",
        text
    )

    text = re.sub(
        r"\bTV\b",
        " TV ",
        text
    )

    text = re.sub(
        r"[^A-Z0-9]+",
        "",
        text
    )

    aliases = {

        "ZEEKERALAM":
            "ZEEKERALAM",

        "ZEEKERALAMHD":
            "ZEEKERALAM",

        "SURYATV":
            "SURYATV",

        "SURYA":
            "SURYATV",

        "SURYAMOVIES":
            "SURYAMOVIES",

        "SURYAMUSIC":
            "SURYAMUSIC",

        "ASIANET":
            "ASIANET",

        "ASIANETPLUS":
            "ASIANETPLUS",

        "ASIANETNEWS":
            "ASIANETNEWS",

        "ASIANETMOVIE":
            "ASIANETMOVIES",

        "ASIANETMOVIESHD":
            "ASIANETMOVIES",

        "FLOWERS":
            "FLOWERS",

        "FLOWERSTV":
            "FLOWERS",

        "AMRITHATV":
            "AMRITATV",

        "AMRITATV":
            "AMRITATV",

        "DDMALAYALAM":
            "DDMALAYALAM",

        "JAIHINDTV":
            "JAIHINDTV",

        "JANAMTV":
            "JANAMTV",

        "KAIRALITV":
            "KAIRALI",

        "KAIRALI":
            "KAIRALI",

        "KAIRALINEWS":
            "KAIRALINEWS",

        "KAIRALIPEOPLETV":
            "KAIRALIPEOPLE",

        "REPORTER":
            "REPORTER",

        "REPORTERTV":
            "REPORTER",

        "RAJMUSIXMALAYALAM":
            "RAJMUSIXMALAYALAM",

        "TWENTYFOUR":
            "TWENTYFOUR",

        "24NEWS":
            "TWENTYFOUR",
    }

    return aliases.get(
        text,
        text
    )


def provider_epg(
    stream_id
):

    try:

        result = api(
            "get_short_epg",
            stream_id=stream_id,
            limit=40
        )

        if not isinstance(
            result,
            dict
        ):
            return []

        listings = (
            result.get(
                "epg_listings"
            )
            or result.get(
                "data"
            )
            or []
        )

        if isinstance(
            listings,
            list
        ):
            return listings

    except Exception as exc:

        print(
            "  Strong8k EPG error:",
            exc
        )

    return []


def simple_epg(
    stream_id
):

    try:

        result = api(
            "get_simple_data_table",
            stream_id=stream_id
        )

        if isinstance(
            result,
            list
        ):
            return result

        if isinstance(
            result,
            dict
        ):

            listings = (
                result.get(
                    "epg_listings"
                )
                or result.get(
                    "data"
                )
                or result.get(
                    "epg"
                )
                or []
            )

            if isinstance(
                listings,
                list
            ):
                return listings

    except Exception as exc:

        print(
            "  Simple EPG error:",
            exc
        )

    return []


def add_provider_programmes(
    tv,
    channel_id,
    listings
):

    count = 0

    for item in listings:

        if not isinstance(
            item,
            dict
        ):
            continue

        start = parse_time(
            item.get(
                "start"
            )
        )

        stop = parse_time(
            item.get(
                "end"
            )
        )

        if (
            not start
            or not stop
            or stop <= start
        ):
            continue

        title = (
            item.get(
                "title"
            )
            or item.get(
                "name"
            )
            or item.get(
                "program"
            )
            or "Unknown programme"
        )

        title = decode_text(
            title
        )

        programme = ET.SubElement(
            tv,
            "programme",
            {
                "start":
                    xmltv_time(start),
                "stop":
                    xmltv_time(stop),
                "channel":
                    channel_id,
            }
        )

        ET.SubElement(
            programme,
            "title"
        ).text = title

        description = (
            item.get(
                "description"
            )
            or item.get(
                "desc"
            )
            or item.get(
                "plot"
            )
        )

        if description:

            ET.SubElement(
                programme,
                "desc"
            ).text = decode_text(
                description
            )

        count += 1

    return count


def download_external():

    print("")
    print(
        "Downloading IPTV-org DishTV EPG..."
    )

    try:

        raw = fetch_bytes(
            EXTERNAL_EPG_URL
        )

        if raw[:2] == b"\x1f\x8b":

            raw = gzip.decompress(
                raw
            )

        print(
            "External EPG size:",
            f"{len(raw):,}",
            "bytes"
        )

        return raw

    except Exception as exc:

        print(
            "External EPG failed:",
            exc
        )

        return None


def parse_external(
    raw
):

    if not raw:
        return {}

    try:

        root = ET.fromstring(
            raw
        )

    except Exception as exc:

        print(
            "Could not parse external EPG:",
            exc
        )

        return {}

    channel_names = {}

    for channel in root.findall(
        "channel"
    ):

        channel_id = (
            channel.get(
                "id"
            )
            or ""
        )

        names = []

        for node in channel.findall(
            "display-name"
        ):

            if node.text:

                names.append(
                    node.text.strip()
                )

        if not names:
            continue

        for name in names:

            key = clean_name(
                name
            )

            if key:

                channel_names[
                    channel_id
                ] = key

                break

    programmes = {}

    for programme in root.findall(
        "programme"
    ):

        source_id = (
            programme.get(
                "channel"
            )
            or ""
        )

        key = channel_names.get(
            source_id
        )

        if not key:
            continue

        start = parse_time(
            programme.get(
                "start"
            )
        )

        stop = parse_time(
            programme.get(
                "stop"
            )
        )

        if (
            not start
            or not stop
            or stop <= start
        ):
            continue

        title_node = (
            programme.find(
                "title"
            )
        )

        if (
            title_node is None
            or not title_node.text
        ):
            continue

        title = decode_text(
            title_node.text
        )

        item = {
            "start": start,
            "stop": stop,
            "title": title,
        }

        desc_node = (
            programme.find(
                "desc"
            )
        )

        if (
            desc_node is not None
            and desc_node.text
        ):

            item[
                "description"
            ] = decode_text(
                desc_node.text
            )

        programmes.setdefault(
            key,
            []
        ).append(
            item
        )

    return programmes


def add_external(
    tv,
    channel_id,
    listings
):

    count = 0

    for item in listings:

        programme = ET.SubElement(
            tv,
            "programme",
            {
                "start":
                    xmltv_time(
                        item["start"]
                    ),
                "stop":
                    xmltv_time(
                        item["stop"]
                    ),
                "channel":
                    channel_id,
            }
        )

        ET.SubElement(
            programme,
            "title"
        ).text = item[
            "title"
        ]

        if item.get(
            "description"
        ):

            ET.SubElement(
                programme,
                "desc"
            ).text = item[
                "description"
            ]

        count += 1

    return count


# =========================================================
# GET STRONG8K CHANNELS
# =========================================================

streams = api(
    "get_live_streams",
    category_id=CATEGORY_ID
)

if not isinstance(
    streams,
    list
):

    raise RuntimeError(
        "Could not retrieve category 255."
    )


streams = [
    stream
    for stream in streams
    if str(
        stream.get(
            "category_id"
        )
    ) == CATEGORY_ID
    and stream.get(
        "stream_id"
    ) is not None
]


if not streams:

    raise RuntimeError(
        "No Malayalam channels found."
    )


print(
    f"Found {len(streams)} Malayalam channels."
)


# =========================================================
# GET EXTERNAL EPG
# =========================================================

external_raw = download_external()

external = parse_external(
    external_raw
)


print(
    f"External channel mappings: "
    f"{len(external)}"
)


# =========================================================
# BUILD XMLTV
# =========================================================

tv = ET.Element(
    "tv",
    {
        "generator-info-name":
            "Malayalam Hybrid EPG"
    }
)


provider_count = 0
external_count = 0
total_programmes = 0


for index, stream in enumerate(
    streams,
    start=1
):

    stream_id = str(
        stream[
            "stream_id"
        ]
    )

    name = str(
        stream.get(
            "name"
        )
        or f"Stream {stream_id}"
    ).strip()

    provider_id = str(
        stream.get(
            "epg_channel_id"
        )
        or ""
    ).strip()

    logo = str(
        stream.get(
            "stream_icon"
        )
        or ""
    ).strip()


    # Keep the provider ID when it is unique.
    # If Strong8k has reused the same ID for another
    # channel, append the stream ID.
    existing_ids = {
        c.get("id")
        for c in tv.findall(
            "channel"
        )
    }

    channel_id = provider_id

    if (
        not channel_id
        or channel_id in existing_ids
    ):

        channel_id = (
            "malayalam-"
            + stream_id
        )


    print("")
    print(
        f"[{index}/{len(streams)}] {name}"
    )


    channel = ET.SubElement(
        tv,
        "channel",
        {
            "id":
                channel_id
        }
    )

    ET.SubElement(
        channel,
        "display-name"
    ).text = name


    if logo:

        ET.SubElement(
            channel,
            "icon",
            {
                "src":
                    logo
            }
        )


    # -----------------------------------------------------
    # STRONG8K
    # -----------------------------------------------------

    listings = provider_epg(
        stream_id
    )

    added = add_provider_programmes(
        tv,
        channel_id,
        listings
    )


    if added == 0:

        listings = simple_epg(
            stream_id
        )

        added = add_provider_programmes(
            tv,
            channel_id,
            listings
        )


    if added:

        provider_count += 1

        total_programmes += added

        print(
            f"  Strong8k: {added} programmes"
        )

        continue


    # -----------------------------------------------------
    # IPTV-ORG / DISHTV
    # -----------------------------------------------------

    key = clean_name(
        name
    )

    matches = external.get(
        key,
        []
    )


    if matches:

        added = add_external(
            tv,
            channel_id,
            matches
        )

        if added:

            external_count += 1

            total_programmes += added

            print(
                f"  IPTV-org: {added} programmes"
            )

            continue


    print(
        "  NO EPG FOUND"
    )


# =========================================================
# SORT PROGRAMMES
# =========================================================

programmes = list(
    tv.findall(
        "programme"
    )
)


for programme in programmes:

    tv.remove(
        programme
    )


programmes.sort(
    key=lambda p: (
        p.get(
            "channel",
            ""
        ),
        p.get(
            "start",
            ""
        )
    )
)


for programme in programmes:

    tv.append(
        programme
    )


# =========================================================
# WRITE XML
# =========================================================

ET.indent(
    tv,
    space="  "
)


ET.ElementTree(
    tv
).write(
    "malayalam.xml",
    encoding="utf-8",
    xml_declaration=True
)


print("")
print("=" * 60)
print(
    f"Malayalam channels: {len(streams)}"
)
print(
    f"Strong8k channels with EPG: "
    f"{provider_count}"
)
print(
    f"IPTV-org channels with EPG: "
    f"{external_count}"
)
print(
    f"Total programmes: "
    f"{total_programmes}"
)
print("=" * 60)


if total_programmes == 0:

    raise RuntimeError(
        "ZERO programmes were generated."
    )
