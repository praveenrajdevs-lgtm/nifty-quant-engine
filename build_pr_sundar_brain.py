#!/usr/bin/env python3
"""
P R Sundar Complete Channel Scraper & Full-Transcript Brain Indexer (~3,300 Videos)
===================================================================================
1. Crawls the official @PRSundar64 Uploads Playlist (UUS2NdYUmv_PUyyKeDAo5zYA, 100 videos/page)
   + @PRSundar64/videos + @PRSundar64/streams + 14 topic searches to enumerate all ~3,300 videos.
2. Classifies every video into Tier 1 ('core_strategy') vs Tier 2 ('daily_market_report').
3. Extracts 100% start-to-end word-by-word timed transcripts via YouTube's InnerTube ANDROID
   player API in parallel (with incremental SQLite checkpointing every 200 videos).
4. Mines all transcripts for high-signal trading rules, firefighting adjustments, option buying
   setups, option selling rules, and common-sense pre-market filters with exact timestamps.
5. Outputs SQLite FTS5 index (data_cache/pr_sundar_brain.db) + JSON (data_cache/pr_sundar_brain.json).
"""

import concurrent.futures
import html as html_lib
import json
import os
import re
import sqlite3
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
CACHE_DIR = BASE_DIR / "data_cache"
CACHE_DIR.mkdir(parents=True, exist_ok=True)
DB_PATH = CACHE_DIR / "pr_sundar_brain.db"
JSON_PATH = CACHE_DIR / "pr_sundar_brain.json"
CATALOG_CACHE = CACHE_DIR / "pr_sundar_catalog_cache.json"

WEB_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
)
ANDROID_UA = "com.google.android.youtube/20.10.38 (Linux; U; Android 11) gzip"
UPLOADS_PLAYLIST_ID = "UUS2NdYUmv_PUyyKeDAo5zYA"

TOPIC_QUERIES = [
    ("option_selling", "option selling strategy"),
    ("option_buying", "option buying strategy"),
    ("firefighting", "firefighting adjustment"),
    ("adjustments", "how to adjust strangle straddle"),
    ("expiry_day", "expiry day strategy"),
    ("strangle_straddle", "strangle straddle strategy"),
    ("ratio_spread", "ratio spread strategy"),
    ("iron_condor", "iron condor butterfly"),
    ("margin_hedging", "margin benefit hedging"),
    ("common_sense", "common sense trading"),
    ("intraday", "intraday option strategy"),
    ("vix_gap", "india vix gap up gap down"),
    ("positional", "positional option selling"),
    ("loss_recovery", "how to avoid loss in options"),
]


def extract_videos_from_yt_json(obj, collected: dict, default_topic: str = "channel_catalog"):
    """Walk YouTube JSON to extract rich videoRenderer / playlistVideoRenderer objects."""
    if isinstance(obj, dict):
        vr = (
            obj.get("videoRenderer")
            or obj.get("gridVideoRenderer")
            or obj.get("playlistVideoRenderer")
        )
        if vr and isinstance(vr, dict) and "videoId" in vr:
            vid = vr["videoId"]
            title = ""
            if "title" in vr:
                runs = vr["title"].get("runs", [])
                if runs:
                    title = "".join(r.get("text", "") for r in runs)
                elif "simpleText" in vr["title"]:
                    title = vr["title"]["simpleText"]
            pub = vr.get("publishedTimeText", {}).get("simpleText", "")
            dur = vr.get("lengthText", {}).get("simpleText", "")
            views_txt = vr.get("viewCountText", {}).get("simpleText", "")
            views_num = 0
            if views_txt:
                digits = re.sub(r"[^0-9]", "", views_txt)
                if digits:
                    views_num = int(digits)
            desc_snip = ""
            if "descriptionSnippet" in vr:
                desc_snip = "".join(
                    r.get("text", "") for r in vr["descriptionSnippet"].get("runs", [])
                )
            if vid not in collected:
                collected[vid] = {
                    "video_id": vid,
                    "title": title,
                    "published_text": pub,
                    "duration": dur,
                    "views_text": views_txt,
                    "views": views_num,
                    "snippet": desc_snip,
                    "topics": [default_topic] if default_topic else [],
                }
            else:
                if default_topic and default_topic not in collected[vid]["topics"]:
                    collected[vid]["topics"].append(default_topic)
                if title and not collected[vid]["title"]:
                    collected[vid]["title"] = title
                if dur and not collected[vid]["duration"]:
                    collected[vid]["duration"] = dur
                if views_num > collected[vid]["views"]:
                    collected[vid]["views"] = views_num
                    collected[vid]["views_text"] = views_txt
        for v in obj.values():
            extract_videos_from_yt_json(v, collected, default_topic)
    elif isinstance(obj, list):
        for item in obj:
            extract_videos_from_yt_json(item, collected, default_topic)


def extract_regex_video_ids(raw_text: str, collected: dict, default_topic: str = "channel_catalog"):
    for vid in re.findall(r'"videoId"\s*:\s*"([a-zA-Z0-9_-]{11})"', raw_text):
        if vid not in collected:
            collected[vid] = {
                "video_id": vid,
                "title": "",
                "published_text": "",
                "duration": "",
                "views_text": "",
                "views": 0,
                "snippet": "",
                "topics": [default_topic] if default_topic else [],
            }
        elif default_topic and default_topic not in collected[vid]["topics"]:
            collected[vid]["topics"].append(default_topic)


def paginate_continuation(initial_html: str, collected: dict, label: str, max_pages: int = 60):
    extract_regex_video_ids(initial_html, collected, "channel_catalog")
    idx = initial_html.find("var ytInitialData = ")
    if idx != -1:
        end_idx = initial_html.find(";</script>", idx)
        if end_idx != -1:
            try:
                data = json.loads(initial_html[idx + len("var ytInitialData = "):end_idx])
                extract_videos_from_yt_json(data, collected, "channel_catalog")
            except Exception:
                pass

    tokens = list(dict.fromkeys(re.findall(r'"token"\s*:\s*"(4qmFsg[^"]+)"', initial_html)))
    next_token = tokens[0] if tokens else None

    page = 1
    stale_pages = 0
    while next_token and page < max_pages:
        page += 1
        try:
            b_req = urllib.request.Request(
                "https://www.youtube.com/youtubei/v1/browse?prettyPrint=false",
                data=json.dumps(
                    {
                        "context": {
                            "client": {
                                "clientName": "WEB",
                                "clientVersion": "2.20241025.01.00",
                                "hl": "en",
                                "gl": "IN",
                            }
                        },
                        "continuation": next_token,
                    }
                ).encode("utf-8"),
                headers={"Content-Type": "application/json", "User-Agent": WEB_UA},
            )
            raw = urllib.request.urlopen(b_req, timeout=20).read().decode("utf-8", errors="ignore")
            before_cnt = len(collected)
            extract_regex_video_ids(raw, collected, "channel_catalog")
            try:
                b_data = json.loads(raw)
                extract_videos_from_yt_json(b_data, collected, "channel_catalog")
            except Exception:
                pass
            new_tokens = list(dict.fromkeys(re.findall(r'"token"\s*:\s*"(4qmFsg[^"]+)"', raw)))
            if len(collected) == before_cnt:
                stale_pages += 1
            else:
                stale_pages = 0
            next_token = new_tokens[0] if new_tokens and stale_pages < 2 else None
            if page % 5 == 0 or not next_token:
                print(f"  [{label}] Page {page}/{max_pages} -> {len(collected):,} unique videos cataloged")
        except Exception as e:
            print(f"  [{label}] Pagination stopped at page {page}: {e}")
            break


def fetch_full_channel_catalog() -> dict:
    collected = {}
    if CATALOG_CACHE.exists():
        try:
            collected = json.loads(CATALOG_CACHE.read_text())
            print(f"Loaded {len(collected):,} cached catalog entries from {CATALOG_CACHE.name}")
        except Exception:
            collected = {}

    # 1. Official Uploads Playlist (100 videos per page -> covers up to ~3,300 videos!)
    print("1A. Crawling @PRSundar64 Official Uploads Playlist (UUS2NdYUmv_PUyyKeDAo5zYA, 100 videos/page)...")
    pl_url = f"https://www.youtube.com/playlist?list={UPLOADS_PLAYLIST_ID}"
    req = urllib.request.Request(pl_url, headers={"User-Agent": WEB_UA, "Accept-Language": "en-US,en;q=0.9"})
    html = urllib.request.urlopen(req, timeout=20).read().decode("utf-8", errors="ignore")
    paginate_continuation(html, collected, "UploadsPlaylist", max_pages=50)

    # 2. Main /videos tab (up to 120 pages = ~3,300 videos)
    print("1B. Crawling @PRSundar64/videos feed across all pages...")
    v_url = "https://www.youtube.com/@PRSundar64/videos"
    v_req = urllib.request.Request(v_url, headers={"User-Agent": WEB_UA, "Accept-Language": "en-US,en;q=0.9"})
    v_html = urllib.request.urlopen(v_req, timeout=20).read().decode("utf-8", errors="ignore")
    paginate_continuation(v_html, collected, "VideosTab", max_pages=120)

    # 3. Main /streams tab (Live trading & Q&A sessions)
    print("1C. Crawling @PRSundar64/streams (Live Sessions)...")
    try:
        s_url = "https://www.youtube.com/@PRSundar64/streams"
        s_req = urllib.request.Request(s_url, headers={"User-Agent": WEB_UA, "Accept-Language": "en-US,en;q=0.9"})
        s_html = urllib.request.urlopen(s_req, timeout=20).read().decode("utf-8", errors="ignore")
        paginate_continuation(s_html, collected, "StreamsTab", max_pages=25)
    except Exception as e:
        print("  Streams tab warning:", e)

    # 4. Topic Searches across 14 strategy categories
    print("1D. Searching @PRSundar64 across 14 specific option strategy topics...")
    for topic_key, query in TOPIC_QUERIES:
        try:
            url = "https://www.youtube.com/@PRSundar64/search?query=" + urllib.parse.quote(query)
            req = urllib.request.Request(
                url, headers={"User-Agent": WEB_UA, "Accept-Language": "en-US,en;q=0.9"}
            )
            t_html = urllib.request.urlopen(req, timeout=15).read().decode("utf-8", errors="ignore")
            idx = t_html.find("var ytInitialData = ")
            if idx != -1:
                end_idx = t_html.find(";</script>", idx)
                if end_idx != -1:
                    data = json.loads(t_html[idx + len("var ytInitialData = "):end_idx])
                    extract_videos_from_yt_json(data, collected, topic_key)
        except Exception as e:
            print(f"  Topic search warning [{topic_key}]: {e}")

    CATALOG_CACHE.write_text(json.dumps(collected, indent=2))
    print(f"Total Unique @PRSundar64 Videos Cataloged & Cached: {len(collected):,}")
    return collected


def parse_timedtext_xml(xml_str: str):
    """Parse YouTube <timedtext format='3'> XML into full start-to-end text and timestamped segments."""
    segments = []
    full_words = []
    for m in re.finditer(r'<p\s+t="(\d+)"[^>]*>(.*?)</p>', xml_str, re.DOTALL):
        t_ms = int(m.group(1))
        inner = m.group(2)
        clean = html_lib.unescape(re.sub(r"<[^>]+>", " ", inner))
        clean = re.sub(r"\s+", " ", clean).strip()
        if clean and clean.lower() not in ("[music]", "[applause]"):
            sec = t_ms // 1000
            segments.append({"t": sec, "text": clean})
            full_words.append(clean)
    full_text = " ".join(full_words)
    return full_text, segments


def fetch_video_transcript(video_id: str) -> dict:
    """Fetch complete video metadata + full start-to-end caption track via InnerTube ANDROID player API."""
    url = "https://www.youtube.com/youtubei/v1/player?prettyPrint=false"
    payload = {
        "context": {
            "client": {
                "clientName": "ANDROID",
                "clientVersion": "20.10.38",
                "androidSdkVersion": 30,
                "hl": "en",
                "gl": "IN",
            }
        },
        "videoId": video_id,
    }
    for attempt in range(2):
        try:
            req = urllib.request.Request(
                url,
                data=json.dumps(payload).encode("utf-8"),
                headers={"Content-Type": "application/json", "User-Agent": ANDROID_UA},
            )
            resp = json.loads(urllib.request.urlopen(req, timeout=15).read().decode("utf-8"))
            vd = resp.get("videoDetails", {})
            micro = resp.get("microformat", {}).get("playerMicroformatRenderer", {})
            title = vd.get("title", "")
            short_desc = vd.get("shortDescription", "")
            views = int(vd.get("viewCount", "0") or 0)
            length_sec = int(vd.get("lengthSeconds", "0") or 0)
            pub_date = micro.get("publishDate", "") or micro.get("uploadDate", "")

            captions = (
                resp.get("captions", {})
                .get("playerCaptionsTracklistRenderer", {})
                .get("captionTracks", [])
            )
            chosen_track = None
            for tr in captions:
                lang = tr.get("languageCode", "")
                if lang.startswith("en"):
                    chosen_track = tr
                    break
            if not chosen_track and captions:
                chosen_track = captions[0]

            transcript_text = ""
            segments = []
            lang_code = ""
            if chosen_track and "baseUrl" in chosen_track:
                lang_code = chosen_track.get("languageCode", "")
                t_req = urllib.request.Request(
                    chosen_track["baseUrl"], headers={"User-Agent": ANDROID_UA}
                )
                xml_raw = urllib.request.urlopen(t_req, timeout=15).read().decode("utf-8", errors="ignore")
                if xml_raw.strip().startswith("<?xml") or "<timedtext" in xml_raw:
                    transcript_text, segments = parse_timedtext_xml(xml_raw)

            return {
                "video_id": video_id,
                "title": title,
                "description": short_desc,
                "views": views,
                "length_seconds": length_sec,
                "publish_date": pub_date,
                "language": lang_code,
                "transcript": transcript_text,
                "word_count": len(transcript_text.split()) if transcript_text else 0,
                "segments": segments,
                "status": "ok" if transcript_text else "no_captions",
            }
        except Exception as e:
            if attempt == 0:
                time.sleep(0.4)
            else:
                return {
                    "video_id": video_id,
                    "error": str(e),
                    "transcript": "",
                    "word_count": 0,
                    "segments": [],
                    "status": "error",
                }


def classify_video_tier_and_categories(title: str, desc: str, transcript: str, existing_topics: list):
    """Separate Tier 1 ('core_strategy') from Tier 2 ('daily_market_report') and assign strategy tags."""
    title_low = (title or "").lower()
    blob = f"{title} {desc} {transcript[:4000]}".lower()
    cats = set(t for t in existing_topics if t != "channel_catalog")

    rules = [
        ("option_selling", ["option selling", "option seller", "short strangle", "short straddle", "theta decay", "time decay", "writing options"]),
        ("option_buying", ["option buying", "option buyer", "buy call", "buy put", "long call", "long put", "gamma blast", "hero or zero"]),
        ("firefighting", ["firefighting", "fire fighting", "adjustment", "adjust", "repair", "roll up", "roll down", "inverted strangle"]),
        ("expiry_day", ["expiry day", "thursday expiry", "tuesday expiry", "zero hero", "gamma"]),
        ("strangle_straddle", ["strangle", "straddle", "iron fly", "iron butterfly", "iron condor"]),
        ("ratio_spread", ["ratio spread", "1:2", "1:3", "backspread", "calendar spread"]),
        ("margin_hedging", ["margin", "hedging", "hedge", "sebi margin", "peak margin", "collateral", "pledge", "liquid bees"]),
        ("common_sense", ["common sense", "open=high", "open=low", "open is equal to", "sgx nifty", "gift nifty", "india vix", "psychology"]),
        ("intraday", ["intraday", "9:20", "9:30", "day trading", "stop loss"]),
        ("positional", ["positional", "overnight", "weekly option", "monthly option"]),
    ]
    for cat, kw_list in rules:
        if any(k in blob for k in kw_list):
            cats.add(cat)

    # Determine if it's a daily pre-market / post-market report vs a core strategy / educational video
    is_daily_report = any(
        p in title_low
        for p in [
            "pre market",
            "pre-market",
            "premarket",
            "market report",
            "post market",
            "what happened in",
            "why market",
            "why nifty",
            "why bank nifty",
            "market today",
            "market tomorrow",
        ]
    )
    has_strategy_title = any(
        p in title_low
        for p in [
            "strategy",
            "option",
            "strangle",
            "straddle",
            "adjust",
            "fire",
            "expiry",
            "margin",
            "hedge",
            "ratio",
            "condor",
            "butterfly",
            "intraday",
            "secret",
            "course",
            "mission",
            "live trade",
            "how i made",
            "loss",
            "profit",
            "vix",
            "common sense",
            "rules",
            "mistake",
        ]
    )
    if has_strategy_title or (len(cats) >= 2 and not is_daily_report):
        video_type = "core_strategy"
    else:
        video_type = "daily_market_report"

    if not cats:
        cats.add("market_analysis")

    return video_type, sorted(cats)


def extract_key_quotes(segments: list, title: str) -> list:
    """Find the highest-signal teaching moments / rules with timestamps inside a video's transcript."""
    signal_phrases = [
        "common sense",
        "strangle",
        "straddle",
        "adjustment",
        "firefighting",
        "fire fighting",
        "option buying",
        "option selling",
        "stop loss",
        "margin",
        "hedge",
        "expiry",
        "ratio spread",
        "iron condor",
        "open is equal to",
        "open high",
        "open low",
        "vix",
        "theta",
        "premium",
        "roll",
        "breakeven",
        "rule",
        "secret",
        "mistake",
    ]
    quotes = []
    if not segments:
        return quotes
    window = []
    win_start = segments[0]["t"]
    for seg in segments:
        window.append(seg["text"])
        if seg["t"] - win_start >= 24:
            chunk = " ".join(window).strip()
            low = chunk.lower()
            score = sum(1 for p in signal_phrases if p in low)
            if score >= 2 and 60 <= len(chunk) <= 440:
                mins = win_start // 60
                secs = win_start % 60
                quotes.append(
                    {
                        "timestamp_sec": win_start,
                        "timestamp_str": f"{mins:02d}:{secs:02d}",
                        "score": score,
                        "quote": chunk,
                    }
                )
            window = []
            win_start = seg["t"]
    quotes.sort(key=lambda x: (-x["score"], x["timestamp_sec"]))
    return quotes[:4]


def ensure_db_schema(conn: sqlite3.Connection):
    cur = conn.cursor()
    # Check if video_type column exists
    cols = [r[1] for r in cur.execute("PRAGMA table_info(videos)").fetchall()]
    if not cols:
        cur.execute(
            """
            CREATE TABLE videos (
                video_id TEXT PRIMARY KEY,
                title TEXT,
                publish_date TEXT,
                published_text TEXT,
                duration TEXT,
                views INTEGER,
                video_type TEXT,
                categories TEXT,
                description TEXT,
                word_count INTEGER,
                transcript TEXT,
                key_quotes_json TEXT,
                status TEXT
            )
            """
        )
        cur.execute(
            """
            CREATE VIRTUAL TABLE IF NOT EXISTS videos_fts USING fts5(
                video_id UNINDEXED,
                title,
                categories,
                description,
                transcript
            )
            """
        )
    else:
        if "video_type" not in cols:
            cur.execute("ALTER TABLE videos ADD COLUMN video_type TEXT DEFAULT 'core_strategy'")
        if "status" not in cols:
            cur.execute("ALTER TABLE videos ADD COLUMN status TEXT DEFAULT ''")
    conn.commit()


def main():
    t0 = time.time()
    conn = sqlite3.connect(str(DB_PATH))
    ensure_db_schema(conn)
    cur = conn.cursor()

    # Load already transcribed video IDs so we don't repeat work
    existing_transcribed = set(
        r[0]
        for r in cur.execute(
            "SELECT video_id FROM videos WHERE word_count > 0 OR status = 'no_captions'"
        ).fetchall()
    )
    print(f"Already have {len(existing_transcribed):,} processed videos in SQLite DB.")

    # Step 1: Enumerate full channel catalog (~3,300 videos)
    catalog = fetch_full_channel_catalog()

    # Prioritize strategy/high-view videos first, then all remaining videos
    to_fetch = []
    for vid, meta in catalog.items():
        if vid in existing_transcribed:
            continue
        topics = [t for t in meta.get("topics", []) if t != "channel_catalog"]
        title_low = (meta.get("title") or "").lower()
        is_strat = bool(topics) or any(
            k in title_low
            for k in [
                "option",
                "strangle",
                "straddle",
                "expiry",
                "adjust",
                "fire",
                "strategy",
                "intraday",
                "margin",
                "hedge",
                "ratio",
                "condor",
                "loss",
                "profit",
                "vix",
                "common sense",
                "buying",
                "selling",
                "live trade",
                "course",
                "mission",
            ]
        )
        to_fetch.append((1 if is_strat else 0, len(topics), meta.get("views", 0), vid))

    to_fetch.sort(reverse=True)
    fetch_ids = [x[3] for x in to_fetch]
    print(f"2. Fetching full start-to-end transcripts for {len(fetch_ids):,} remaining videos (24 parallel threads)...")

    batch_size = 200
    for b_start in range(0, len(fetch_ids), batch_size):
        batch = fetch_ids[b_start : b_start + batch_size]
        batch_results = {}
        with concurrent.futures.ThreadPoolExecutor(max_workers=24) as pool:
            fmap = {pool.submit(fetch_video_transcript, vid): vid for vid in batch}
            for fut in concurrent.futures.as_completed(fmap):
                vid = fmap[fut]
                batch_results[vid] = fut.result()

        # Save checkpoint batch into SQLite
        for vid, tr in batch_results.items():
            meta = catalog.get(vid, {})
            title = tr.get("title") or meta.get("title") or ""
            desc = tr.get("description") or meta.get("snippet") or ""
            transcript_txt = tr.get("transcript", "")
            views = max(meta.get("views", 0), tr.get("views", 0))
            pub_date = tr.get("publish_date", "")
            pub_txt = meta.get("published_text", "")
            dur = meta.get("duration", "")
            if not dur and tr.get("length_seconds"):
                s = tr["length_seconds"]
                dur = f"{s // 60}:{s % 60:02d}"
            v_type, cats = classify_video_tier_and_categories(
                title, desc, transcript_txt, meta.get("topics", [])
            )
            quotes = extract_key_quotes(tr.get("segments", []), title)
            wc = tr.get("word_count", 0)
            status = tr.get("status", "")

            cur.execute(
                """
                INSERT OR REPLACE INTO videos
                (video_id, title, publish_date, published_text, duration, views, video_type,
                 categories, description, word_count, transcript, key_quotes_json, status)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    vid,
                    title,
                    pub_date,
                    pub_txt,
                    dur,
                    views,
                    v_type,
                    ",".join(cats),
                    desc[:1500],
                    wc,
                    transcript_txt,
                    json.dumps(quotes),
                    status,
                ),
            )
        conn.commit()

        done_so_far = min(b_start + batch_size, len(fetch_ids))
        tot_cat = cur.execute("SELECT COUNT(*) FROM videos").fetchone()[0]
        tot_tr = cur.execute("SELECT COUNT(*) FROM videos WHERE word_count > 0").fetchone()[0]
        tot_words = cur.execute("SELECT COALESCE(SUM(word_count), 0) FROM videos").fetchone()[0]
        tot_strat = cur.execute("SELECT COUNT(*) FROM videos WHERE video_type = 'core_strategy' AND word_count > 0").fetchone()[0]
        print(
            f"   [Checkpoint {done_so_far:,}/{len(fetch_ids):,}] "
            f"DB Videos: {tot_cat:,} | Full Transcripts: {tot_tr:,} ({tot_strat:,} Core Strategy) | "
            f"Total Spoken Words: {tot_words:,} | Elapsed: {time.time() - t0:.1f}s"
        )

    # Backfill video_type for any initial rows from earlier run
    rows_to_update = cur.execute(
        "SELECT video_id, title, description, transcript, categories FROM videos WHERE video_type IS NULL OR video_type = ''"
    ).fetchall()
    for r in rows_to_update:
        v_type, cats = classify_video_tier_and_categories(
            r[1], r[2], r[3] or "", (r[4] or "").split(",")
        )
        cur.execute(
            "UPDATE videos SET video_type = ?, categories = ? WHERE video_id = ?",
            (v_type, ",".join(cats), r[0]),
        )
    conn.commit()

    # Rebuild FTS5 index cleanly
    print("3. Rebuilding SQLite FTS5 Full-Text Search Index...")
    cur.execute("DROP TABLE IF EXISTS videos_fts")
    cur.execute(
        """
        CREATE VIRTUAL TABLE videos_fts USING fts5(
            video_id UNINDEXED,
            title,
            video_type,
            categories,
            description,
            transcript
        )
        """
    )
    cur.execute(
        """
        INSERT INTO videos_fts (video_id, title, video_type, categories, description, transcript)
        SELECT video_id, title, video_type, categories, description, transcript
        FROM videos
        WHERE word_count > 0 OR title != ''
        """
    )
    conn.commit()

    # Export updated JSON summary
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    total_cataloged = cur.execute("SELECT COUNT(*) FROM videos").fetchone()[0]
    total_transcribed = cur.execute("SELECT COUNT(*) FROM videos WHERE word_count > 0").fetchone()[0]
    total_core_strategy = cur.execute(
        "SELECT COUNT(*) FROM videos WHERE video_type = 'core_strategy' AND word_count > 0"
    ).fetchone()[0]
    total_daily_reports = cur.execute(
        "SELECT COUNT(*) FROM videos WHERE video_type = 'daily_market_report' AND word_count > 0"
    ).fetchone()[0]
    total_words = cur.execute("SELECT COALESCE(SUM(word_count), 0) FROM videos").fetchone()[0]
    total_views = cur.execute("SELECT COALESCE(SUM(views), 0) FROM videos").fetchone()[0]

    top_videos_rows = cur.execute(
        """
        SELECT video_id, title, publish_date, published_text, duration, views, video_type, categories,
               description, word_count, key_quotes_json, substr(transcript, 1, 900) AS transcript_preview
        FROM videos
        WHERE word_count > 50
        ORDER BY
            CASE WHEN video_type = 'core_strategy' THEN 1 ELSE 0 END DESC,
            views DESC
        LIMIT 120
        """
    ).fetchall()

    top_videos = []
    for r in top_videos_rows:
        top_videos.append(
            {
                "video_id": r["video_id"],
                "url": f"https://www.youtube.com/watch?v={r['video_id']}",
                "title": r["title"],
                "publish_date": r["publish_date"] or r["published_text"],
                "duration": r["duration"],
                "views": r["views"],
                "video_type": r["video_type"],
                "categories": r["categories"].split(",") if r["categories"] else [],
                "word_count": r["word_count"],
                "quotes": json.loads(r["key_quotes_json"] or "[]"),
                "transcript_preview": r["transcript_preview"],
            }
        )

    existing_json = {}
    if JSON_PATH.exists():
        try:
            existing_json = json.loads(JSON_PATH.read_text())
        except Exception:
            existing_json = {}

    brain_payload = {
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S IST"),
        "channel": {
            "name": "P R Sundar",
            "handle": "@PRSundar64",
            "url": "https://www.youtube.com/@PRSundar64",
            "total_videos_cataloged": total_cataloged,
            "total_transcripts_indexed": total_transcribed,
            "core_strategy_transcripts": total_core_strategy,
            "daily_report_transcripts": total_daily_reports,
            "total_spoken_words_indexed": total_words,
            "total_views_cataloged": total_views,
        },
        "synthesized_playbook": existing_json.get("synthesized_playbook", []),
        "videos": top_videos,
    }
    JSON_PATH.write_text(json.dumps(brain_payload, indent=2))
    conn.close()

    print(
        f"\nCOMPLETE in {time.time() - t0:.1f}s!\n"
        f"  Total Videos Cataloged : {total_cataloged:,}\n"
        f"  Full Transcripts Saved : {total_transcribed:,} (Core Strategy: {total_core_strategy:,} | Daily Reports: {total_daily_reports:,})\n"
        f"  Total Spoken Words     : {total_words:,} words\n"
    )


if __name__ == "__main__":
    main()
