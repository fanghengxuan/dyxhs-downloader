"""Xiaohongshu (RedNote) note parsing and download.

Walks the note page's embedded ``window.__INITIAL_STATE__`` for video streams
or image lists. When the page refuses anonymous access, falls back to yt-dlp
(which can reuse browser cookies) for video notes.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from urllib.parse import urlparse

import requests

from .common import (
    DESKTOP_UA,
    MOBILE_UA,
    DownloadError,
    download_file,
    extract_first_url,
    load_browser_cookies,
    load_netscape_cookies,
    sanitize,
    unique_path,
)

_NOTE_ID_RE = re.compile(r"/(?:explore|discovery/item|note)/([0-9a-fA-F]{24})")
_STATE_RE = re.compile(r"window\.__INITIAL_STATE__\s*=\s*(.*?)</script>", re.DOTALL)
_UNDEFINED_RE = re.compile(r"(?<=[:,\[])\s*undefined\s*(?=[,}\]])")

BASE_HEADERS = {
    "User-Agent": DESKTOP_UA,
    "Accept-Language": "zh-CN,zh;q=0.9",
    "Referer": "https://www.xiaohongshu.com/",
}


class XhsError(DownloadError):
    pass


def _note_id(url: str) -> str | None:
    match = _NOTE_ID_RE.search(url)
    return match.group(1) if match else None


def _extract_state(html: str) -> dict:
    match = _STATE_RE.search(html)
    if not match:
        raise XhsError("页面里没有 __INITIAL_STATE__，可能被登录墙或验证码拦住了")
    raw = _UNDEFINED_RE.sub("null", match.group(1))
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        raise XhsError(f"__INITIAL_STATE__ 不是合法 JSON: {exc}") from exc


def _pick_note(state: dict, note_id: str | None) -> dict:
    # Desktop layout
    detail_map = ((state.get("note") or {}).get("noteDetailMap") or {})
    if detail_map:
        detail = detail_map.get(note_id or "") or next(iter(detail_map.values()))
        note = detail.get("note") or {}
        if note:
            return note

    # Mobile layout (used when the desktop page redirects to login)
    mobile_note = (((state.get("noteData") or {}).get("data") or {}).get("noteData") or {})
    if mobile_note:
        return mobile_note

    raise XhsError("笔记数据为空：链接可能失效、被删除，或需要登录（可加 --cookies）")


def _video_candidates(note: dict) -> list[tuple[str, str]]:
    streams = (((note.get("video") or {}).get("media") or {}).get("stream") or {})
    candidates: list[tuple[str, str]] = []
    for codec in ("h264", "h265", "av1", "h266", "hevc"):
        for entry in streams.get(codec) or []:
            urls = [entry.get("masterUrl")] + list(entry.get("backupUrls") or [])
            for url in urls:
                if url:
                    candidates.append((codec, url))
    origin_key = (((note.get("video") or {}).get("consumer") or {}).get("originVideoKey"))
    if origin_key:
        candidates.append(("origin", f"https://sns-video-bd.xhscdn.com/{origin_key}"))
    return candidates


def _best_video(note: dict) -> tuple[str, str]:
    streams = (((note.get("video") or {}).get("media") or {}).get("stream") or {})
    codec_rank = {"h264": 3, "h265": 2, "hevc": 2, "av1": 1, "h266": 0}
    scored: list[tuple[int, int, int, str, str]] = []
    for codec in ("h264", "h265", "av1", "h266", "hevc"):
        for entry in streams.get(codec) or []:
            url = entry.get("masterUrl")
            if not url:
                continue
            pixels = int(entry.get("width") or 0) * int(entry.get("height") or 0)
            bitrate = int(entry.get("avgBitrate") or entry.get("videoBitrate") or 0)
            scored.append((pixels, codec_rank.get(codec, 0), bitrate, codec, url))
    if scored:
        scored.sort(reverse=True)
        _, _, _, codec, url = scored[0]
        return codec, url
    candidates = _video_candidates(note)
    if candidates:
        return candidates[0]
    raise XhsError("笔记里没有找到视频流（如果是图文笔记，应该走图片分支）")


def _image_urls(note: dict) -> list[str]:
    urls = []
    for image in note.get("imageList") or []:
        url = image.get("urlDefault")
        if not url:
            for info in image.get("infoList") or []:
                if info.get("imageScene") == "WB_DFT" and info.get("url"):
                    url = info["url"]
                    break
        if not url:
            for info in image.get("infoList") or []:
                if info.get("url"):
                    url = info["url"]
                    break
        if url:
            urls.append(url)
    return urls


def make_session(cookies: str | None = None, browser: str | None = None) -> requests.Session:
    session = requests.Session()
    session.headers.update(BASE_HEADERS)
    if cookies:
        load_netscape_cookies(session, cookies)
    if browser:
        load_browser_cookies(session, browser)
    return session


def parse(url: str, session: requests.Session | None = None) -> dict:
    """Return note metadata plus ``kind``/``video_url``/``image_urls``."""
    url = extract_first_url(url) or url
    session = session or make_session()

    session.get("https://www.xiaohongshu.com/explore", timeout=20)
    resp = session.get(url, timeout=30, allow_redirects=True)
    resp.raise_for_status()

    if "/404" in resp.url:
        raise XhsError("笔记页跳到了 404：作品可能已删除/不可见，或链接缺少有效的 xsec_token")

    if "/login" in resp.url:
        # Mobile share pages embed the note server-side even without login.
        session.headers["User-Agent"] = MOBILE_UA
        resp = session.get(url, timeout=30, allow_redirects=True)
        session.headers["User-Agent"] = DESKTOP_UA
        resp.raise_for_status()
        if "/login" in resp.url:
            raise XhsError(
                "小红书要求登录：用 Cookie-Editor 导出 cookies.txt 后传给 --cookies"
                "（--browser 在 Edge/Chrome 新版本上可能因 App-Bound Encryption 失败）"
            )

    note_id = _note_id(resp.url) or _note_id(url)
    state = _extract_state(resp.text)
    note = _pick_note(state, note_id)

    note_id = note.get("noteId") or note_id or "unknown"
    title = (note.get("title") or "").strip()
    desc = (note.get("desc") or "").strip()
    if not title:
        title = desc.splitlines()[0] if desc else note_id

    result = {"note_id": note_id, "title": title, "desc": desc, "kind": note.get("type")}
    if note.get("type") == "video" or note.get("video"):
        codec, video_url = _best_video(note)
        return {**result, "kind": "video", "codec": codec, "video_url": video_url, "image_urls": []}

    images = _image_urls(note)
    if images:
        return {**result, "kind": "images", "video_url": None, "image_urls": images}
    raise XhsError("既没有视频流也没有图片列表，页面结构可能变了")


def _download_with_ytdlp(url: str, out_dir: Path, cookies: str | None, browser: str | None) -> list[Path]:
    try:
        from yt_dlp import YoutubeDL
        from yt_dlp.utils import DownloadError as YtDlpError
    except ImportError as exc:
        raise XhsError("需要 yt-dlp 才能兜底，请先 pip install yt-dlp") from exc

    opts = {
        "outtmpl": str(out_dir / "%(title).60s_%(id)s.%(ext)s"),
        "quiet": True,
        "noprogress": True,
        "noplaylist": True,
    }
    if browser:
        opts["cookiesfrombrowser"] = (browser,)
    elif cookies:
        opts["cookiefile"] = cookies

    print("  用 yt-dlp 兜底解析视频...")
    out_dir.mkdir(parents=True, exist_ok=True)
    before = {p for p in out_dir.iterdir() if p.is_file()}
    try:
        with YoutubeDL(opts) as ydl:
            ydl.download([url])
    except YtDlpError as exc:
        raise XhsError(f"yt-dlp 也失败了: {exc}") from exc
    return sorted(p for p in out_dir.iterdir() if p.is_file() and p not in before)


def _image_ext(url: str) -> str:
    path = urlparse(url).path
    suffix = Path(path).suffix.lower()
    return suffix if suffix in {".jpg", ".jpeg", ".png", ".webp", ".gif"} else ".jpg"


def download(
    url: str,
    out_dir: Path,
    cookies: str | None = None,
    browser: str | None = None,
) -> list[Path]:
    session = make_session(cookies=cookies, browser=browser)

    try:
        info = parse(url, session=session)
    except XhsError as exc:
        print(f"  直接解析失败：{exc}")
        print("  尝试 yt-dlp 兜底...")
        return _download_with_ytdlp(url, out_dir, cookies, browser)

    print(f"小红书: {info['title']} ({'视频' if info['kind'] == 'video' else '图文'})")
    out_dir.mkdir(parents=True, exist_ok=True)

    if info["kind"] == "video":
        base = sanitize(info["title"], info["note_id"])
        name = f"{base}_{info['note_id']}.mp4" if base != info["note_id"] else f"{info['note_id']}.mp4"
        dest = unique_path(out_dir / name)
        print(f"  编码: {info['codec']}")
        return [download_file(session, info["video_url"], dest, headers=BASE_HEADERS, label=dest.name)]

    folder = unique_path(out_dir / sanitize(f"{info['title']}_{info['note_id']}", info["note_id"]))
    folder.mkdir(parents=True, exist_ok=True)
    paths = []
    for index, image_url in enumerate(info["image_urls"], start=1):
        dest = folder / f"{index:02d}{_image_ext(image_url)}"
        print(f"  图片 {index}/{len(info['image_urls'])}")
        paths.append(download_file(session, image_url, dest, headers=BASE_HEADERS, label=dest.name))
    return paths
