"""Read-only engagement for a submitted video."""
import re
from urllib.parse import urlencode

from providers import request, required, youtube_access_token


def engagement(platform, video_id):
    if platform == "youtube":
        if not re.fullmatch(r"[A-Za-z0-9_-]{11}", video_id):
            raise ValueError("Invalid YouTube video ID.")
        url = "https://www.googleapis.com/youtube/v3/videos?" + urlencode({
            "part": "statistics", "id": video_id,
        })
        result, _ = request(url, token=youtube_access_token())
        stats = result["items"][0]["statistics"]
        return {name: int(stats[key]) for name, key in (
            ("views", "viewCount"), ("likes", "likeCount"), ("comments", "commentCount")
        ) if key in stats}

    if platform != "facebook" or not re.fullmatch(r"[0-9]+", video_id):
        raise ValueError("Invalid Facebook video ID.")
    version = required("FACEBOOK_GRAPH_VERSION")
    if not re.fullmatch(r"v[0-9]+\.[0-9]+", version):
        raise ValueError("Invalid Facebook Graph API version.")
    token = required("FACEBOOK_PAGE_TOKEN")
    base = f"https://graph.facebook.com/{version}/{video_id}"
    counts = {}
    for edge in ("likes", "comments"):
        result, _ = request(base + f"/{edge}?summary=true&limit=0", token=token)
        total = result.get("summary", {}).get("total_count")
        if total is not None:
            counts[edge] = int(total)
    return counts
