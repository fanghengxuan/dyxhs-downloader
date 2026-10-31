"""Shared helpers for the Douyin / Xiaohongshu downloader."""

from __future__ import annotations

import re
import sys
from pathlib import Path

import requests

DESKTOP_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)
MOBILE_UA = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_2 like Mac OS X) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) EdgiOS/121.0.2277.107 "
    "Version/17.0 Mobile/15E148 Safari/604.1"
)

_URL_RE = re.compile(r"https?://[^\s<>\"']+")
_BAD_CHARS = re.compile(r'[\\/:*?"<>|\r\n\t]')


class DownloadError(RuntimeError):
    """Raised when a page or media file cannot be fetched."""


def setup_console() -> None:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except AttributeError:
            pass


def extract_first_url(text: str) -> str | None:
    match = _URL_RE.search(text)
    return match.group(0).rstrip("，。,.!！?？)）]】") if match else None


def detect_platform(text: str) -> str | None:
    url = extract_first_url(text) or ""
    if "douyin.com" in url or "iesdouyin.com" in url:
        return "douyin"
    if "xiaohongshu.com" in url or "xhslink.com" in url:
        return "xhs"
    return None


def sanitize(name: str, fallback: str = "untitled", limit: int = 60) -> str:
    name = _BAD_CHARS.sub("_", name or "").strip(" ._")
    name = re.sub(r"\s+", " ", name)
    return (name[:limit].strip() or fallback)


def load_netscape_cookies(session: requests.Session, path: str | Path) -> None:
    """Load a Netscape-format cookies.txt exported by a browser extension."""
    path = Path(path)
    if not path.exists():
        raise DownloadError(f"Cookie 文件不存在: {path}")
    count = 0
    with path.open(encoding="utf-8", errors="ignore") as fh:
        for line in fh:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = line.split("\t")
            if len(parts) != 7:
                continue
            domain, _flag, cookie_path, _secure, _expiry, name, value = parts
            session.cookies.set(name, value, domain=domain, path=cookie_path)
            count += 1
    if count == 0:
        raise DownloadError(f"Cookie 文件为空或格式不对: {path}")


def load_browser_cookies(session: requests.Session, browser: str, domain: str = "xiaohongshu.com") -> None:
    """Copy matching cookies from a local browser using yt-dlp's extractor."""
    try:
        from yt_dlp.cookies import extract_cookies_from_browser
    except ImportError as exc:
        raise DownloadError("读取浏览器 cookie 需要 yt-dlp，请先 pip install yt-dlp") from exc

    try:
        jar = extract_cookies_from_browser(browser)
    except Exception as exc:
        raise DownloadError(
            f"从 {browser} 读取 cookie 失败: {exc}。"
            "Edge/Chrome 127+ 的 App-Bound Encryption 会让自动读取失效，"
            "推荐用 Cookie-Editor 导出 cookies.txt 后传给 --cookies"
        ) from exc

    count = 0
    for cookie in jar:
        if domain in (cookie.domain or ""):
            session.cookies.set(cookie.name, cookie.value)
            count += 1
    if not count:
        raise DownloadError(f"{browser} 里没有找到 {domain} 的 cookie，请先在浏览器登录小红书")
    print(f"已从 {browser} 读取 {count} 条 {domain} cookie")


def download_file(
    session: requests.Session,
    url: str,
    dest: Path,
    headers: dict[str, str] | None = None,
    label: str | None = None,
) -> Path:
    """Stream a URL to disk with a simple percentage display."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    with session.get(url, headers=headers, stream=True, timeout=60) as resp:
        resp.raise_for_status()
        total = int(resp.headers.get("content-length") or 0)
        done = 0
        last_step = -5
        with dest.open("wb") as fh:
            for chunk in resp.iter_content(chunk_size=256 * 1024):
                if not chunk:
                    continue
                fh.write(chunk)
                done += len(chunk)
                if total:
                    pct = done / total * 100
                    if pct - last_step >= 5 or done == total:
                        print(f"\r  {label or dest.name}: {pct:5.1f}%", end="", flush=True)
                        last_step = pct
        if total:
            print()
    if dest.stat().st_size == 0:
        dest.unlink(missing_ok=True)
        raise DownloadError(f"下载到空文件: {url}")
    return dest


def unique_path(path: Path) -> Path:
    if not path.exists():
        return path
    stem, suffix, parent = path.stem, path.suffix, path.parent
    for i in range(2, 1000):
        candidate = parent / f"{stem}_{i}{suffix}"
        if not candidate.exists():
            return candidate
    raise DownloadError(f"同名文件过多: {path}")
