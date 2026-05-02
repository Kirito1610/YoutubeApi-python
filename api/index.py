import time
from typing import Any, Dict, List

from flask import Flask, jsonify
from yt_dlp import YoutubeDL

app = Flask(__name__)

CACHE_TTL_SECONDS = 60 * 60
_cache: Dict[str, Dict[str, Any]] = {}


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
    }

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
        return jsonify({"error": str(exc)}), 500


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
        return jsonify({"error": str(exc)}), 500
