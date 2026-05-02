import base64
import os
import tempfile
import time
from typing import Any, Dict, List

from flask import Flask, jsonify
from yt_dlp import YoutubeDL

app = Flask(__name__)

CACHE_TTL_SECONDS = 60 * 60
_cache: Dict[str, Dict[str, Any]] = {}
_cookies_file_cache: str | None = None


def _resolve_cookies_file() -> str | None:
    global _cookies_file_cache
    if _cookies_file_cache:
        return _cookies_file_cache

    # 1) Preferred for Vercel: set YTDLP_COOKIES_B64 with base64-encoded
    # Netscape-format cookie content.
    cookies_b64 = os.getenv("YTDLP_COOKIES_B64")
    if cookies_b64:
        try:
            cookie_content = base64.b64decode(cookies_b64).decode("utf-8")
            temp_path = os.path.join(tempfile.gettempdir(), "yt_cookies.txt")
            with open(temp_path, "w", encoding="utf-8") as cookie_file:
                cookie_file.write(cookie_content)
            _cookies_file_cache = temp_path
            return _cookies_file_cache
        except Exception:
            # Fall through to other cookie sources.
            pass

    # 2) Plain text env var alternative.
    cookies_text = os.getenv("YTDLP_COOKIES")
    if cookies_text:
        temp_path = os.path.join(tempfile.gettempdir(), "yt_cookies.txt")
        with open(temp_path, "w", encoding="utf-8") as cookie_file:
            cookie_file.write(cookies_text)
        _cookies_file_cache = temp_path
        return _cookies_file_cache

    # 3) Local dev fallback: project root cookies.txt
    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    local_cookie_file = os.path.join(project_root, "cookies.txt")
    if os.path.exists(local_cookie_file):
        _cookies_file_cache = local_cookie_file
        return _cookies_file_cache

    return None


def _extract_video_info(video_id: str) -> Dict[str, Any]:
    cached = _cache.get(video_id)
    now = time.time()
    if cached and now - cached["timestamp"] < CACHE_TTL_SECONDS:
        return cached["info"]

    url = f"https://www.youtube.com/watch?v={video_id}"
    ydl_opts = {
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
        "extractor_args": {"youtube": {"player_client": ["android", "web"]}},
        "http_headers": {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            )
        },
    }
    cookie_file = _resolve_cookies_file()
    if cookie_file:
        ydl_opts["cookiefile"] = cookie_file

    with YoutubeDL(ydl_opts) as ydl:
        data = ydl.extract_info(url, download=False)

    formats = data.get("formats", [])

    video_formats = [
        f
        for f in formats
        if f.get("vcodec") != "none" and f.get("height") and f.get("url")
    ]

    best_per_quality: Dict[int, Dict[str, Any]] = {}
    for item in video_formats:
        height = int(item["height"])
        current = best_per_quality.get(height)
        if not current or (item.get("tbr") or 0) > (current.get("tbr") or 0):
            best_per_quality[height] = item

    videos: List[Dict[str, Any]] = [
        {
            "quality": f"{fmt['height']}p",
            "formatId": fmt.get("format_id"),
            "ext": fmt.get("ext"),
            "videoUrl": fmt.get("url"),
        }
        for fmt in sorted(best_per_quality.values(), key=lambda x: x["height"])
    ]

    audio_candidates = [
        f
        for f in formats
        if f.get("vcodec") == "none" and f.get("acodec") not in (None, "none") and f.get("url")
    ]
    audio_candidates.sort(key=lambda x: x.get("abr") or 0, reverse=True)
    best_audio = audio_candidates[0] if audio_candidates else None

    info = {
        "title": data.get("title"),
        "thumbnail": data.get("thumbnail"),
        "audio": best_audio.get("url") if best_audio else None,
        "videos": videos,
    }
    _cache[video_id] = {"timestamp": now, "info": info}
    return info


@app.get("/api/video/<video_id>")
def get_video(video_id: str):
    try:
        return jsonify(_extract_video_info(video_id))
    except Exception as exc:  # pragma: no cover
        error_message = str(exc)
        if "Sign in to confirm you" in error_message:
            error_message = (
                "YouTube blocked this request. Configure YTDLP_COOKIES_B64 (recommended) "
                "or YTDLP_COOKIES in Vercel environment variables."
            )
        return jsonify({"error": error_message}), 500


@app.get("/stream/<video_id>")
def get_stream(video_id: str):
    try:
        info = _extract_video_info(video_id)
        stream_url = None

        # Serverless-friendly response: return direct stream URL for the top quality.
        if info.get("videos"):
            stream_url = info["videos"][-1].get("videoUrl")

        return jsonify({"stream": stream_url, "audio": info.get("audio")})
    except Exception as exc:  # pragma: no cover
        error_message = str(exc)
        if "Sign in to confirm you" in error_message:
            error_message = (
                "YouTube blocked this request. Configure YTDLP_COOKIES_B64 (recommended) "
                "or YTDLP_COOKIES in Vercel environment variables."
            )
        return jsonify({"error": error_message}), 500
