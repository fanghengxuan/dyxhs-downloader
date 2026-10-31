"""Douyin share-link parsing and download.

Two paths:

1. Direct SSR parse (ported from Mithranda/agent-reach-douyin, MIT): fetch the
   share page and read ``window._ROUTER_DATA``. Works only when Douyin still
   renders ``item_list`` server-side; in 2026 it usually does not.
2. yt-dlp with browser cookies. Douyin's detail API needs "fresh cookies (not
   necessarily logged in)", so this is the reliable path.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import requests

from .common import DESKTOP_UA, MOBILE_UA, DownloadError, download_file, extract_first_url, sanitize, unique_path

_ROUTER_RE = re.compile(r"window\._ROUTER_DATA\s*=\s*(.*?)</script>", re.DOTALL)
_VIDEO_ID_RE = re.compile(r"(?:video|note)/(\d{10,25})")


def _video_id_from_url(url: str) -> str | None:
    match = _VIDEO_ID_RE.search(url)
    if match:
        return match.group(1)
    tail = url.split("?")[0].rstrip("/").split("/")[-1]
    return tail if tail.isdigit() else None


def resolve(share_text: str, session: requests.Session | None = None) -> tuple[str, str]:
    """Follow the share link and return ``(canonical_url, video_id)``."""
    share_url = extract_first_url(share_text)
    if not share_url:
        raise DownloadError("没有在文本里找到抖音链接")

    session = session or requests.Session()
    resp = session.get(
        share_url,
        headers={"User-Agent": MOBILE_UA},
        timeout=30,
        allow_redirects=True,
    )
    resp.raise_for_status()
    video_id = _video_id_from_url(resp.url)
    if not video_id:
        raise DownloadError(f"没能从跳转地址里解析出作品 ID: {resp.url}")
    return f"https://www.douyin.com/video/{video_id}", video_id


def _parse_ssr(video_id: str, session: requests.Session) -> dict:
    page_url = f"https://www.iesdouyin.com/share/video/{video_id}"
    resp = session.get(page_url, headers={"User-Agent": MOBILE_UA}, timeout=30)
    resp.raise_for_status()

    match = _ROUTER_RE.search(resp.text)
    if not match:
        raise DownloadError("分享页里没有找到 _ROUTER_DATA，抖音改版了")
    try:
        router = json.loads(match.group(1).strip())
    except json.JSONDecodeError as exc:
        raise DownloadError(f"_ROUTER_DATA 不是合法 JSON: {exc}") from exc

    loader = router.get("loaderData") or {}
    item_list = None
    for key in ("video_(id)/page", "note_(id)/page"):
        info = (loader.get(key) or {}).get("videoInfoRes") or {}
        if info.get("item_list"):
            item_list = info["item_list"]
            break
    if not item_list:
        raise DownloadError("分享页没有返回 item_list（页面是客户端渲染的空壳）")

    item = item_list[0]
    if item.get("images") and not (item.get("video") or {}).get("play_addr"):
        raise DownloadError("这是抖音图文作品，当前版本只下载视频")

    urls = ((item.get("video") or {}).get("play_addr") or {}).get("url_list") or []
    if not urls:
        raise DownloadError("没有找到视频播放地址（play_addr 为空）")

    title = (item.get("desc") or "").strip()
    return {
        "video_id": video_id,
        "title": title,
        "url": urls[0].replace("playwm", "play"),
        "source": "ssr",
    }


def _capture_with_browser(video_id: str) -> dict:
    """Load the video page in headless Edge/Chrome and capture the detail API.

    Douyin's web detail endpoint requires cookies produced by its JS challenge.
    A fresh headless browser passes the challenge anonymously, and the page
    fires ``/aweme/v1/web/aweme/detail/`` with the play address we need.
    """
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise DownloadError("需要 playwright：pip install playwright（使用系统已装的 Edge/Chrome）") from exc

    found: dict = {}

    def handle_response(response):
        if "/aweme/v1/web/aweme/detail/" not in response.url:
            return
        try:
            detail = (response.json() or {}).get("aweme_detail") or {}
        except Exception:
            return
        if str(detail.get("aweme_id")) != str(video_id):
            return
        urls = (((detail.get("video") or {}).get("play_addr") or {}).get("url_list") or [])
        if urls and not found:
            found.update(
                video_id=video_id,
                title=(detail.get("desc") or "").strip(),
                url=urls[0],
                source="browser",
            )

    with sync_playwright() as pw:
        browser = None
        last_error = None
        for channel in ("msedge", "chrome", "chromium"):
            try:
                browser = pw.chromium.launch(channel=channel, headless=True)
                break
            except Exception as exc:  # channel not installed
                last_error = exc
        if browser is None:
            raise DownloadError(f"没有找到可用的 Edge/Chrome: {last_error}")

        try:
            context = browser.new_context(locale="zh-CN", user_agent=DESKTOP_UA)
            page = context.new_page()
            page.on("response", handle_response)
            page.goto(f"https://www.douyin.com/video/{video_id}", wait_until="domcontentloaded", timeout=60000)
            page.wait_for_timeout(6000)
            if not found:
                page.wait_for_timeout(4000)
            if not found:
                raise DownloadError(f"浏览器打开了页面但没有抓到详情接口（当前页面: {page.url}）")
        except DownloadError:
            raise
        except Exception as exc:
            raise DownloadError(f"headless 浏览器加载抖音页面失败: {exc}") from exc
        finally:
            browser.close()

    return found


def _ytdlp_opts(cookies: str | None, browser: str | None) -> dict:
    opts = {"quiet": True, "noprogress": True, "noplaylist": True}
    if browser:
        opts["cookiesfrombrowser"] = (browser,)
    elif cookies:
        opts["cookiefile"] = cookies
    return opts


def _ytdlp_info(canonical_url: str, cookies: str | None, browser: str | None) -> dict:
    try:
        from yt_dlp import YoutubeDL
        from yt_dlp.utils import DownloadError as YtDlpError
    except ImportError as exc:
        raise DownloadError("需要 yt-dlp 才能带 cookie 解析抖音，请先 pip install yt-dlp") from exc

    opts = _ytdlp_opts(cookies, browser)
    try:
        with YoutubeDL(opts) as ydl:
            info = ydl.extract_info(canonical_url, download=False)
    except YtDlpError as exc:
        raise DownloadError(f"yt-dlp 解析失败: {exc}") from exc
    return {
        "video_id": info.get("id"),
        "title": info.get("title") or "",
        "url": info.get("url"),
        "source": "yt-dlp",
    }


def _ytdlp_download(canonical_url: str, out_dir: Path, cookies: str | None, browser: str | None) -> Path:
    try:
        from yt_dlp import YoutubeDL
        from yt_dlp.utils import DownloadError as YtDlpError
    except ImportError as exc:
        raise DownloadError("需要 yt-dlp 才能带 cookie 下载抖音，请先 pip install yt-dlp") from exc

    opts = _ytdlp_opts(cookies, browser)
    opts["outtmpl"] = str(out_dir / "%(title).60s_%(id)s.%(ext)s")
    out_dir.mkdir(parents=True, exist_ok=True)
    before = {p for p in out_dir.iterdir() if p.is_file()}
    try:
        with YoutubeDL(opts) as ydl:
            ydl.download([canonical_url])
    except YtDlpError as exc:
        raise DownloadError(f"yt-dlp 下载失败: {exc}") from exc
    new_files = sorted(p for p in out_dir.iterdir() if p.is_file() and p not in before)
    if not new_files:
        raise DownloadError("yt-dlp 报告成功，但没有找到新文件")
    return new_files[0]


def _auto_hint(exc: Exception) -> DownloadError:
    return DownloadError(
        f"{exc}。抖音需要浏览器自动化：先 pip install playwright（会用系统已装的 Edge/Chrome），"
        "或提供 --cookies cookies.txt / --browser edge"
    )


def _save_browser_info(video_id: str, canonical: str, cookies: str | None, browser: str | None) -> dict:
    print("  直连 SSR 不可用，改用 headless 浏览器抓详情...")
    try:
        return _capture_with_browser(video_id)
    except DownloadError as exc:
        if cookies or browser:
            print(f"  浏览器抓取失败（{exc}），改用 yt-dlp + cookie...")
            return _ytdlp_info(canonical, cookies, browser)
        raise _auto_hint(exc) from exc


def parse(
    link: str,
    session: requests.Session | None = None,
    cookies: str | None = None,
    browser: str | None = None,
) -> dict:
    session = session or requests.Session()
    canonical, video_id = resolve(link, session)
    try:
        return _parse_ssr(video_id, session)
    except DownloadError as exc:
        print(f"  SSR 解析失败（{exc}）")
        return _save_browser_info(video_id, canonical, cookies, browser)


def download(
    link: str,
    out_dir: Path,
    cookies: str | None = None,
    browser: str | None = None,
) -> Path:
    session = requests.Session()
    canonical, video_id = resolve(link, session)
    try:
        info = _parse_ssr(video_id, session)
    except DownloadError as exc:
        print(f"  SSR 解析失败（{exc}）")
        info = _save_browser_info(video_id, canonical, cookies, browser)
        if info.get("source") == "yt-dlp":
            return _ytdlp_download(canonical, out_dir, cookies, browser)

    base = sanitize(info["title"], info["video_id"])
    name = f"{base}.mp4" if base == info["video_id"] else f"{base}_{info['video_id']}.mp4"
    dest = unique_path(out_dir / name)
    print(f"抖音: {info['title'] or info['video_id']}")
    headers = {"User-Agent": MOBILE_UA if info.get("source") == "ssr" else DESKTOP_UA}
    if info.get("source") != "ssr":
        headers["Referer"] = "https://www.douyin.com/"
    return download_file(session, info["url"], dest, headers=headers, label=dest.name)
