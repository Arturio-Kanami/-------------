#!/usr/bin/env python3
"""Download Xiaoe videos that are already playable in the user's browser session."""

from __future__ import annotations

import argparse
import asyncio
import os
import re
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Iterable, List, Optional
from urllib.parse import unquote, urlparse


MEDIA_EXTENSIONS = (".m3u8", ".mp4")
MEDIA_CONTENT_TYPES = (
    "application/vnd.apple.mpegurl",
    "application/x-mpegurl",
    "audio/mpegurl",
    "video/mp4",
)
DRM_HINTS = ("widevine", "fairplay", "playready", "/license", "license/v1")


@dataclass
class MediaCandidate:
    url: str
    kind: str
    page_title: str = ""
    referer: str = ""
    headers: Dict[str, str] = field(default_factory=dict)
    content_type: str = ""
    first_seen: float = field(default_factory=time.time)
    hits: int = 1


def sanitize_filename(value: str, fallback: str = "xiaoe_video") -> str:
    value = unquote(value or "").strip()
    value = re.sub(r"[\\/:*?\"<>|]+", "_", value)
    value = re.sub(r"\s+", " ", value).strip(" .")
    return value[:120] or fallback


def guess_kind(url: str, content_type: str = "") -> Optional[str]:
    lower_url = url.lower().split("?", 1)[0]
    lower_type = (content_type or "").lower().split(";", 1)[0].strip()
    if lower_url.endswith(".m3u8") or "mpegurl" in lower_type:
        return "m3u8"
    if lower_url.endswith(".mp4") or lower_type == "video/mp4":
        return "mp4"
    return None


def default_browser_path() -> Optional[str]:
    candidates = [
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    ]
    for item in candidates:
        if Path(item).exists():
            return item
    return None


def default_ffmpeg_path() -> Optional[str]:
    env_path = os.environ.get("FFMPEG")
    if env_path and Path(env_path).exists():
        return env_path

    bundled = Path(__file__).resolve().parent / "tools" / "ffmpeg.exe"
    if bundled.exists():
        return str(bundled)

    lel_path = Path(r"E:\？？？？\LEL-Downloader\Source\ffmpeg.exe")
    if lel_path.exists():
        return str(lel_path)

    found = shutil.which("ffmpeg")
    return found


def build_cookie_header(cookies: Iterable[dict]) -> str:
    parts = []
    for cookie in cookies:
        name = cookie.get("name")
        value = cookie.get("value")
        if name and value is not None:
            parts.append(f"{name}={value}")
    return "; ".join(parts)


def normalize_header_lines(headers: Dict[str, str], cookie_header: str) -> str:
    allow = {
        "accept",
        "accept-language",
        "origin",
        "referer",
        "user-agent",
    }
    lines = []
    seen = set()
    for key, value in headers.items():
        lower = key.lower()
        if lower in allow and value:
            canonical = "-".join(part.capitalize() for part in lower.split("-"))
            lines.append(f"{canonical}: {value}")
            seen.add(lower)
    if cookie_header:
        lines.append(f"Cookie: {cookie_header}")
        seen.add("cookie")
    if "user-agent" not in seen:
        lines.append("User-Agent: Mozilla/5.0")
    return "\r\n".join(lines) + "\r\n"


def make_output_path(output_dir: Path, candidate: MediaCandidate, index: int, media_type: str = "video") -> Path:
    parsed = urlparse(candidate.url)
    url_name = Path(parsed.path).stem
    title = candidate.page_title or url_name or f"video_{index:02d}"
    suffix = ".m4a" if media_type == "audio" else ".mp4"
    filename = sanitize_filename(title, f"video_{index:02d}") + suffix
    path = output_dir / filename
    if not path.exists():
        return path
    stem = path.stem
    for n in range(2, 1000):
        alt = output_dir / f"{stem}_{n}{suffix}"
        if not alt.exists():
            return alt
    return output_dir / f"{stem}_{int(time.time())}{suffix}"


async def download_with_ffmpeg(context, candidate: MediaCandidate, output_path: Path, ffmpeg: str, media_type: str = "video") -> None:
    cookies = await context.cookies(candidate.url)
    cookie_header = build_cookie_header(cookies)
    header_lines = normalize_header_lines(candidate.headers, cookie_header)

    cmd = [
        ffmpeg,
        "-hide_banner",
        "-loglevel",
        "info",
        "-y",
        "-headers",
        header_lines,
        "-i",
        candidate.url,
    ]
    if candidate.kind == "m3u8":
        cmd[1:1] = [
            "-protocol_whitelist",
            "file,http,https,tcp,tls,crypto",
            "-allowed_extensions",
            "ALL",
        ]
    if media_type == "audio":
        cmd.extend(["-vn", "-map", "0:a:0", "-c:a", "copy"])
    else:
        cmd.extend(["-c", "copy"])
    if candidate.kind == "m3u8":
        cmd.extend(["-bsf:a", "aac_adtstoasc"])
    cmd.append(str(output_path))

    print(f"\nDownloading {'audio' if media_type == 'audio' else 'video'} to: {output_path}")
    proc = subprocess.run(cmd)
    if proc.returncode != 0:
        raise RuntimeError(f"ffmpeg failed with exit code {proc.returncode}")


def print_candidates(candidates: List[MediaCandidate]) -> None:
    if not candidates:
        print("No m3u8/mp4 media URLs captured yet.")
        return
    print("\nCaptured media URLs:")
    for idx, item in enumerate(candidates, start=1):
        parsed = urlparse(item.url)
        short_url = item.url
        if len(short_url) > 150:
            short_url = short_url[:110] + "..." + short_url[-35:]
        print(f"{idx:>2}. [{item.kind}] hits={item.hits} host={parsed.netloc}")
        if item.page_title:
            print(f"    title: {item.page_title}")
        if item.content_type:
            print(f"    type:  {item.content_type}")
        print(f"    url:   {short_url}")


async def main_async(args: argparse.Namespace) -> int:
    try:
        from playwright.async_api import async_playwright
    except ImportError:
        print("Missing dependency: playwright")
        print("Run: python -m pip install -r requirements.txt")
        return 2

    browser_path = args.browser or default_browser_path()
    if not browser_path:
        print("Chrome/Edge was not found. Pass --browser C:\\path\\to\\chrome.exe")
        return 2

    ffmpeg = args.ffmpeg or default_ffmpeg_path()
    if not ffmpeg or not Path(ffmpeg).exists():
        print("ffmpeg was not found. Pass --ffmpeg C:\\path\\to\\ffmpeg.exe")
        return 2

    output_dir = Path(args.output).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    profile_dir = Path(args.profile).resolve()
    profile_dir.mkdir(parents=True, exist_ok=True)

    candidates_by_url: Dict[str, MediaCandidate] = {}
    drm_hits: List[str] = []

    async with async_playwright() as p:
        context = await p.chromium.launch_persistent_context(
            user_data_dir=str(profile_dir),
            executable_path=browser_path,
            headless=False,
            viewport={"width": 1280, "height": 900},
            args=[
                "--disable-blink-features=AutomationControlled",
                "--autoplay-policy=no-user-gesture-required",
            ],
        )

        page = context.pages[0] if context.pages else await context.new_page()

        async def remember_from_response(response) -> None:
            url = response.url
            lower = url.lower()
            if any(hint in lower for hint in DRM_HINTS):
                drm_hits.append(url)
            try:
                headers = await response.request.all_headers()
            except Exception:
                headers = {}
            content_type = response.headers.get("content-type", "")
            kind = guess_kind(url, content_type)
            if not kind:
                return
            title = ""
            try:
                title = await response.request.frame.page.title()
            except Exception:
                try:
                    title = await page.title()
                except Exception:
                    title = ""
            existing = candidates_by_url.get(url)
            if existing:
                existing.hits += 1
                existing.page_title = title or existing.page_title
                return
            candidates_by_url[url] = MediaCandidate(
                url=url,
                kind=kind,
                page_title=title,
                referer=headers.get("referer", ""),
                headers=headers,
                content_type=content_type,
            )
            print(f"\nCaptured {kind}: {url[:140]}")

        def attach_page(target_page) -> None:
            target_page.on("response", lambda response: asyncio.create_task(remember_from_response(response)))

        attach_page(page)
        for existing_page in context.pages:
            if existing_page is not page:
                attach_page(existing_page)
        context.on("page", attach_page)

        if args.url:
            await page.goto(args.url, wait_until="domcontentloaded")
        else:
            await page.goto("https://study.xiaoe-tech.com/t_l/learnLogin#/wx", wait_until="domcontentloaded")

        print("\nBrowser is open.")
        print("Log in normally, open a purchased lesson, start playback, then return here.")
        print("This script only records media requested by your authorized browser session.")

        while True:
            action = await asyncio.to_thread(input, "\nPress Enter after playback starts, or type q then Enter to quit: ")
            if action.strip().lower() == "q":
                break
            candidates = sorted(candidates_by_url.values(), key=lambda item: item.first_seen)
            print_candidates(candidates)
            if drm_hits:
                print("\nDRM-like license requests were seen. If the video is DRM-protected, this tool will not bypass it.")
            if not candidates:
                continue

            choice = await asyncio.to_thread(input, "\nChoose number to download, 'a' for all, 'r' to keep recording, or 'q' to quit: ")
            choice = choice.strip().lower()
            if choice == "q":
                break
            if choice == "r" or not choice:
                continue
            if choice == "a":
                selected = list(enumerate(candidates, start=1))
            else:
                try:
                    selected_index = int(choice)
                    selected = [(selected_index, candidates[selected_index - 1])]
                except (ValueError, IndexError):
                    print("Invalid choice.")
                    continue

            for idx, candidate in selected:
                media_type = "audio" if args.audio_only else "video"
                output_path = make_output_path(output_dir, candidate, idx, media_type)
                try:
                    await download_with_ffmpeg(context, candidate, output_path, ffmpeg, media_type)
                    print(f"Done: {output_path}")
                except Exception as exc:
                    print(f"Download failed: {exc}")

        await context.close()
    return 0


def parse_args(argv: List[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Capture and download authorized Xiaoe m3u8/mp4 media.")
    parser.add_argument("url", nargs="?", help="Optional Xiaoe shop/course/lesson URL to open.")
    parser.add_argument("--output", default="downloads", help="Output directory. Default: downloads")
    parser.add_argument("--profile", default=".xiaoe_browser_profile", help="Persistent browser profile directory.")
    parser.add_argument("--browser", help="Path to Chrome or Edge executable.")
    parser.add_argument("--ffmpeg", help="Path to ffmpeg executable.")
    parser.add_argument("--audio-only", action="store_true", help="Save only the first audio track as .m4a.")
    return parser.parse_args(argv)


def main(argv: List[str]) -> int:
    args = parse_args(argv)
    try:
        return asyncio.run(main_async(args))
    except KeyboardInterrupt:
        print("\nStopped.")
        return 130


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
