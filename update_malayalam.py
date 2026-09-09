import os
import re
import urllib.request
import urllib.parse
import json
import base64
from collections import defaultdict


SERVER = os.environ["XTREAM_SERVER"].rstrip("/")
USERNAME = os.environ["XTREAM_USERNAME"].strip()
PASSWORD = os.environ["XTREAM_PASSWORD"].strip()

CATEGORY_ID = "255"

OUTPUT_FILE = "malayalam.xml"

SHORT_EPG_LIMIT = 100


def clean_text(value):
    if value is None:
        return ""

    value = str(value)
    value = re.sub(r"\s+", " ", value)

    return value.strip()


def decode_value(value):
    if not value:
        return ""

    value = str(value).strip()

    # Try normal Base64 decoding first
    try:
        padded = value + "=" * (-len(value) % 4)
        decoded = base64.b64decode(
            padded,
            validate=False
        ).decode(
            "utf-8",
            errors="ignore"
        ).strip()

        if decoded:
            return decoded
    except Exception:
        pass

    return value


def request_json(url):
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 Malayalam-EPG-Updater"
        }
    )

    with urllib.request.urlopen(
        request,
        timeout=60
    ) as response:

        data = response.read()

    return json.loads(
        data.decode(
            "utf-8",
            errors="ignore"
        )
    )


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

        stream_id = str(
            item.get("stream_id", "")
        ).strip()

        if not stream_id:
            continue

        channels.append({
            "stream_id": stream_id,
            "name": clean_text(
                item.get("name", "")
            ),
            "epg_id": clean_text(
                item.get("epg_channel_id", "")
            ),
            "logo": clean_text(
                item.get("stream_icon", "")
            )
        })

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

        return data.get(
            "epg_listings",
            []
        )

    except Exception as e:

        print(
            f"SHORT EPG ERROR "
            f"{stream_id}: {e}"
        )

        return []


def get_simple_data_table(stream_id):

    url = (
        f"{SERVER}/player_api.php?"
        f"username={urllib.parse.quote(USERNAME)}&"
        f"password={urllib.parse.quote(PASSWORD)}&"
        f"action=get_simple_data_table&"
        f"stream_id={urllib.parse.quote(stream_id)}"
    )

    try:

        data = request_json(url)

        # Normal Xtream response
        if isinstance(data, dict):

            listings = data.get(
                "epg_listings",
                []
            )

            if listings:
                return listings

            # Some providers return the
            # listings under another key.
            for key in (
                "epg",
                "data",
                "listings"
            ):

                if isinstance(
                    data.get(key),
                    list
                ):
                    return data[key]

        # Some providers return a list directly
        if isinstance(data, list):
            return data

        return []

    except Exception as e:

        print(
            f"SIMPLE TABLE ERROR "
            f"{stream_id}: {e}"
        )

        return []


def normalise_programme(item):

    start = clean_text(
        item.get("start")
        or item.get("start_time")
        or ""
    )

    stop = clean_text(
        item.get("end")
        or item.get("stop")
        or item.get("end_time")
        or ""
    )

    title = decode_value(
        item.get("title")
        or item.get("name")
        or ""
    )

    description = decode_value(
        item.get("description")
        or item.get("desc")
        or ""
    )

    if not start or not stop or not title:
        return None

    return {
        "start": start,
        "stop": stop,
        "title": clean_text(title),
        "description": clean_text(description)
    }


def xml_escape(value):

    return (
        str(value)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&apos;")
    )


def make_channel_id(channel):

    # Always make the XMLTV ID unique.
    #
    # This avoids the previous problem where several
    # channels were all using IDs such as:
    # Surya.in
    # AsianetNews.in

    return f"malayalam-{channel['stream_id']}"


def add_programmes(
    destination,
    channel_id,
    listings
):

    seen = {
        (
            p["start"],
            p["stop"],
            p["title"]
        )
        for p in destination[channel_id]
    }

    added = 0

    for item in listings:

        programme = normalise_programme(item)

        if not programme:
            continue

        key = (
            programme["start"],
            programme["stop"],
            programme["title"]
        )

        if key in seen:
            continue

        destination[channel_id].append(
            programme
        )

        seen.add(key)
        added += 1

    return added


def main():

    channels = get_malayalam_channels()

    print(
        f"Malayalam channels: "
        f"{len(channels)}"
    )

    strong8k_epg_channels = sum(
        1
        for c in channels
        if c["epg_id"]
    )

    print(
        f"Strong8k channels with EPG: "
        f"{strong8k_epg_channels}"
    )

    programmes = defaultdict(list)

    short_total = 0
    simple_total = 0

    short_channels = 0
    simple_channels = 0

    print()
    print(
        "Querying both EPG endpoints "
        "for every Malayalam channel..."
    )
    print()

    for number, channel in enumerate(
        channels,
        start=1
    ):

        stream_id = channel["stream_id"]
        channel_id = make_channel_id(
            channel
        )

        print(
            f"[{number}/{len(channels)}] "
            f"{channel['name']} "
            f"(stream {stream_id})"
        )

        # ------------------------------------------
        # SHORT EPG
        # ------------------------------------------

        short = get_short_epg(
            stream_id
        )

        short_added = add_programmes(
            programmes,
            channel_id,
            short
        )

        if short_added:
            short_channels += 1

        short_total += short_added

        print(
            f"    Short EPG: "
            f"{len(short)} returned, "
            f"{short_added} added"
        )

        # ------------------------------------------
        # FULL SIMPLE DATA TABLE
        # ------------------------------------------

        simple = get_simple_data_table(
            stream_id
        )

        simple_added = add_programmes(
            programmes,
            channel_id,
            simple
        )

        if simple_added:
            simple_channels += 1

        simple_total += simple_added

        print(
            f"    Simple table: "
            f"{len(simple)} returned, "
            f"{simple_added} added"
        )

    # ----------------------------------------------
    # BUILD XMLTV
    # ----------------------------------------------

    lines = []

    lines.append(
        '<?xml version="1.0" encoding="UTF-8"?>'
    )

    lines.append(
        '<tv generator-info-name='
        '"Malayalam Strong8k EPG updater">'
    )

    # CHANNELS

    for channel in channels:

        channel_id = make_channel_id(
            channel
        )

        lines.append(
            f'  <channel id="'
            f'{xml_escape(channel_id)}">'
        )

        lines.append(
            f'    <display-name>'
            f'{xml_escape(channel["name"])}'
            f'</display-name>'
        )

        if channel["logo"]:

            lines.append(
                f'    <icon src="'
                f'{xml_escape(channel["logo"])}"/>'
            )

        lines.append(
            "  </channel>"
        )

    # PROGRAMMES

    total_programmes = 0

    for channel in channels:

        channel_id = make_channel_id(
            channel
        )

        channel_programmes = programmes.get(
            channel_id,
            []
        )

        channel_programmes.sort(
            key=lambda p: p["start"]
        )

        for programme in channel_programmes:

            lines.append(
                f'  <programme '
                f'start="{xml_escape(programme["start"])}" '
                f'stop="{xml_escape(programme["stop"])}" '
                f'channel="{xml_escape(channel_id)}">'
            )

            lines.append(
                f'    <title>'
                f'{xml_escape(programme["title"])}'
                f'</title>'
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

    lines.append(
        "</tv>"
    )

    with open(
        OUTPUT_FILE,
        "w",
        encoding="utf-8"
    ) as f:

        f.write(
            "\n".join(lines)
        )

    # ----------------------------------------------
    # FINAL DIAGNOSTICS
    # ----------------------------------------------

    channels_with_programmes = sum(
        1
        for channel in channels
        if programmes.get(
            make_channel_id(channel)
        )
    )

    print()
    print(
        "======================================"
    )
    print(
        "Malayalam EPG generation complete"
    )
    print(
        "======================================"
    )

    print(
        f"Malayalam channels: "
        f"{len(channels)}"
    )

    print(
        f"Strong8k channels with EPG: "
        f"{strong8k_epg_channels}"
    )

    print(
        f"Short EPG channels: "
        f"{short_channels}"
    )

    print(
        f"Simple table channels: "
        f"{simple_channels}"
    )

    print(
        f"Short EPG programmes added: "
        f"{short_total}"
    )

    print(
        f"Simple table programmes added: "
        f"{simple_total}"
    )

    print(
        f"Channels with any programmes: "
        f"{channels_with_programmes}"
    )

    print(
        f"Total programmes: "
        f"{total_programmes}"
    )

    print(
        "======================================"
    )


if __name__ == "__main__":
    main()
