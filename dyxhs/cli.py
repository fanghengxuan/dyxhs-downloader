"""Command line entry point for the Douyin / Xiaohongshu downloader."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import requests

from . import douyin, xhs
from .common import DownloadError, detect_platform, setup_console


def _print_info(info: dict) -> None:
    print(json.dumps(info, ensure_ascii=False, indent=2))


def main(argv: list[str] | None = None) -> int:
    setup_console()
    parser = argparse.ArgumentParser(
        prog="dyxhs",
        description="下载抖音 / 小红书作品。直接粘贴分享链接或整段分享文本。",
    )
    parser.add_argument("links", nargs="+", help="抖音或小红书分享链接 / 分享文本")
    parser.add_argument(
        "-o",
        "--out",
        default=str(Path.home() / "Downloads" / "dyxhs"),
        help="保存目录（默认 ~/Downloads/dyxhs）",
    )
    parser.add_argument("--cookies", help="Netscape 格式 cookies.txt（小红书登录态）")
    parser.add_argument("--browser", help="从浏览器读取 cookie，如 chrome / edge / firefox（小红书）")
    parser.add_argument("--info", action="store_true", help="只解析并打印信息，不下载")
    args = parser.parse_args(argv)

    out_dir = Path(args.out).expanduser()
    failed = 0

    for raw in args.links:
        platform = detect_platform(raw)
        if platform is None:
            print(f"错误: 无法识别平台，只支持抖音 / 小红书链接: {raw}", file=sys.stderr)
            failed += 1
            continue

        try:
            if platform == "douyin":
                if args.info:
                    _print_info(douyin.parse(raw, cookies=args.cookies, browser=args.browser))
                else:
                    path = douyin.download(raw, out_dir, cookies=args.cookies, browser=args.browser)
                    print(f"完成: {path}")
            else:
                if args.info:
                    session = xhs.make_session(cookies=args.cookies, browser=args.browser)
                    info = xhs.parse(raw, session=session)
                    info["image_count"] = len(info["image_urls"])
                    info.pop("image_urls", None)
                    _print_info(info)
                else:
                    paths = xhs.download(raw, out_dir, cookies=args.cookies, browser=args.browser)
                    for path in paths:
                        print(f"完成: {path}")
        except (DownloadError, requests.RequestException) as exc:
            print(f"错误: {exc}", file=sys.stderr)
            failed += 1

    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
