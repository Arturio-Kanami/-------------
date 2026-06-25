#!/usr/bin/env python3
"""Local web UI for authorized Xiaoe video capture/download and transcription."""

from __future__ import annotations

import asyncio
import hashlib
import json
import locale
import mimetypes
import os
import shutil
import site
import subprocess
import sys
import threading
import time
import webbrowser
from dataclasses import asdict, dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Dict, List, Optional
from urllib.parse import unquote, urlparse


ROOT = Path(__file__).resolve().parents[1]
STATIC_DIR = Path(__file__).resolve().parent / "static"
DOWNLOAD_DIR = ROOT / "downloads"
TRANSCRIPT_DIR = ROOT / "transcripts"
PROFILE_DIR = ROOT / ".xiaoe_browser_profile"
MODELS_DIR = ROOT / "models"
DEFAULT_LOGIN_URL = "https://study.xiaoe-tech.com/t_l/learnLogin#/wx"
NVIDIA_DLL_SUBDIRS = (
    Path("nvidia") / "cublas" / "bin",
    Path("nvidia") / "cudnn" / "bin",
    Path("nvidia") / "cuda_nvrtc" / "bin",
)


MEDIA_CONTENT_TYPES = (
    "application/vnd.apple.mpegurl",
    "application/x-mpegurl",
    "audio/mpegurl",
    "video/mp4",
)
DRM_HINTS = ("widevine", "fairplay", "playready", "/license", "license/v1")


@dataclass
class MediaCandidate:
    id: str
    url: str
    kind: str
    host: str
    page_title: str = ""
    headers: Dict[str, str] = field(default_factory=dict)
    content_type: str = ""
    first_seen: float = field(default_factory=time.time)
    hits: int = 1


@dataclass
class Job:
    id: str
    kind: str
    label: str
    status: str = "queued"
    progress: Optional[float] = None
    output: str = ""
    error: str = ""
    started_at: float = field(default_factory=time.time)
    finished_at: Optional[float] = None


class AppState:
    def __init__(self) -> None:
        self.lock = threading.RLock()
        self.logs: List[dict] = []
        self.candidates: Dict[str, MediaCandidate] = {}
        self.jobs: Dict[str, Job] = {}
        self.drm_hits: List[str] = []
        self.capture_running = False
        self.capture_url = ""
        self.browser_path = default_browser_path() or ""
        self.ffmpeg_path = default_ffmpeg_path() or ""
        self.playwright_loop: Optional[asyncio.AbstractEventLoop] = None
        self.playwright = None
        self.context = None
        self.page = None

    def log(self, message: str, level: str = "info") -> None:
        item = {"ts": time.time(), "level": level, "message": message}
        with self.lock:
            self.logs.append(item)
            self.logs = self.logs[-400:]
        print(f"[{level}] {message}", flush=True)

    def snapshot(self) -> dict:
        with self.lock:
            return {
                "capture_running": self.capture_running,
                "capture_url": self.capture_url,
                "browser_path": self.browser_path,
                "ffmpeg_path": self.ffmpeg_path,
                "download_dir": str(DOWNLOAD_DIR),
                "transcript_dir": str(TRANSCRIPT_DIR),
                "candidates": [asdict(item) for item in sorted(self.candidates.values(), key=lambda x: x.first_seen)],
                "jobs": [asdict(item) for item in sorted(self.jobs.values(), key=lambda x: x.started_at, reverse=True)],
                "logs": list(self.logs[-220:]),
                "downloads": list_media_files(DOWNLOAD_DIR),
                "transcripts": list_transcript_files(TRANSCRIPT_DIR),
                "models": list_models(),
                "drm_seen": bool(self.drm_hits),
                "gpu": gpu_status(),
            }

def default_browser_path() -> Optional[str]:
    for item in [
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    ]:
        if Path(item).exists():
            return item
    return None


def default_ffmpeg_path() -> Optional[str]:
    env_path = os.environ.get("FFMPEG")
    if env_path and Path(env_path).exists():
        return env_path
    bundled = ROOT / "tools" / "ffmpeg.exe"
    if bundled.exists():
        return str(bundled)
    for root in [Path("E:/"), Path("C:/")]:
        if root.exists():
            try:
                for child in root.iterdir():
                    try:
                        found = child / "LEL-Downloader" / "Source" / "ffmpeg.exe"
                        if found.exists():
                            return str(found)
                    except OSError:
                        continue
            except OSError:
                pass
    return shutil.which("ffmpeg")


def gpu_status() -> dict:
    try:
        nvidia = subprocess.run(["nvidia-smi"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False).returncode == 0
    except Exception:
        nvidia = False
    cublas_path = find_on_path("cublas64_12.dll")
    cudnn_path = find_on_path("cudnn_ops64_9.dll") or find_on_path("cudnn64_9.dll")
    return {
        "nvidia": nvidia,
        "cublas": bool(cublas_path),
        "cudnn": bool(cudnn_path),
        "cublas_path": cublas_path,
        "cudnn_path": cudnn_path,
        "ready": nvidia and bool(cublas_path) and bool(cudnn_path),
    }


def find_on_path(name: str) -> str:
    found = shutil.which(name)
    if found:
        return found
    for directory in nvidia_runtime_dirs():
        target = directory / name
        if target.exists():
            return str(target)
    if os.name != "nt":
        return ""
    try:
        result = subprocess.run(["where.exe", name], capture_output=True, text=True, check=False)
    except Exception:
        return ""
    if result.returncode != 0:
        return ""
    return result.stdout.splitlines()[0].strip()


def nvidia_runtime_dirs() -> List[Path]:
    roots = []
    try:
        roots.extend(Path(p) for p in site.getsitepackages())
    except Exception:
        pass
    user_site = site.getusersitepackages()
    if user_site:
        roots.append(Path(user_site))

    dirs: List[Path] = []
    seen = set()
    for root in roots:
        for subdir in NVIDIA_DLL_SUBDIRS:
            path = root / subdir
            key = str(path).lower()
            if path.exists() and key not in seen:
                dirs.append(path)
                seen.add(key)
    return dirs


def add_nvidia_runtime_to_path() -> None:
    current_path = os.environ.get("PATH", "")
    current_parts = {part.lower() for part in current_path.split(os.pathsep) if part}
    prepend = []
    for path in nvidia_runtime_dirs():
        text = str(path)
        if text.lower() not in current_parts:
            prepend.append(text)
        if hasattr(os, "add_dll_directory"):
            try:
                os.add_dll_directory(text)
            except OSError:
                pass
    if prepend:
        os.environ["PATH"] = os.pathsep.join(prepend + [current_path])


def guess_kind(url: str, content_type: str = "") -> Optional[str]:
    lower_url = url.lower().split("?", 1)[0]
    lower_type = (content_type or "").lower().split(";", 1)[0].strip()
    if lower_url.endswith(".m3u8") or "mpegurl" in lower_type:
        return "m3u8"
    if lower_url.endswith(".mp4") or lower_type == "video/mp4":
        return "mp4"
    return None


def candidate_id(url: str) -> str:
    return hashlib.sha1(url.encode("utf-8", "ignore")).hexdigest()[:12]


def clean_name(value: str, fallback: str) -> str:
    import re

    value = unquote(value or "").strip()
    value = re.sub(r'[\\/:*?"<>|]+', "_", value)
    value = re.sub(r"\s+", " ", value).strip(" .")
    return value[:120] or fallback


def short_path(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(ROOT))
    except ValueError:
        return str(path)


def list_media_files(folder: Path) -> List[dict]:
    suffixes = {".mp4", ".mkv", ".mov", ".webm", ".m4a", ".mp3", ".wav", ".flac"}
    if not folder.exists():
        return []
    files = []
    for item in sorted(folder.rglob("*"), key=lambda p: p.stat().st_mtime if p.exists() else 0, reverse=True):
        if item.is_file() and item.suffix.lower() in suffixes:
            stat = item.stat()
            files.append({"name": item.name, "path": str(item), "short_path": short_path(item), "size": stat.st_size, "mtime": stat.st_mtime})
    return files[:200]


def list_transcript_files(folder: Path) -> List[dict]:
    suffixes = {".txt"}
    if not folder.exists():
        return []
    files = []
    for item in sorted(folder.rglob("*"), key=lambda p: p.stat().st_mtime if p.exists() else 0, reverse=True):
        if item.is_file() and item.suffix.lower() in suffixes:
            stat = item.stat()
            files.append({"name": item.name, "path": str(item), "short_path": short_path(item), "size": stat.st_size, "mtime": stat.st_mtime})
    return files[:200]


def list_models() -> List[str]:
    if not MODELS_DIR.exists():
        return []
    return sorted([p.name.replace("faster-whisper-", "") for p in MODELS_DIR.glob("faster-whisper-*") if (p / "model.bin").exists()])


STATE = AppState()


def build_cookie_header(cookies: List[dict]) -> str:
    return "; ".join(f"{c.get('name')}={c.get('value')}" for c in cookies if c.get("name") and c.get("value") is not None)


def header_lines(headers: Dict[str, str], cookie_header: str) -> str:
    allow = {"accept", "accept-language", "origin", "referer", "user-agent"}
    lines = []
    seen = set()
    for key, value in headers.items():
        lower = key.lower()
        if lower in allow and value:
            lines.append(f"{'-'.join(part.capitalize() for part in lower.split('-'))}: {value}")
            seen.add(lower)
    if cookie_header:
        lines.append(f"Cookie: {cookie_header}")
    if "user-agent" not in seen:
        lines.append("User-Agent: Mozilla/5.0")
    return "\r\n".join(lines) + "\r\n"


def make_output_path(candidate: MediaCandidate, media_type: str = "video") -> Path:
    parsed = urlparse(candidate.url)
    base = clean_name(candidate.page_title or Path(parsed.path).stem, "xiaoe_video")
    suffix = ".m4a" if media_type == "audio" else ".mp4"
    target = DOWNLOAD_DIR / f"{base}{suffix}"
    if not target.exists():
        return target
    for i in range(2, 1000):
        alt = DOWNLOAD_DIR / f"{base}_{i}{suffix}"
        if not alt.exists():
            return alt
    return DOWNLOAD_DIR / f"{base}_{int(time.time())}{suffix}"


def ensure_loop() -> asyncio.AbstractEventLoop:
    if STATE.playwright_loop and STATE.playwright_loop.is_running():
        return STATE.playwright_loop

    loop = asyncio.new_event_loop()
    STATE.playwright_loop = loop

    def runner() -> None:
        asyncio.set_event_loop(loop)
        loop.run_forever()

    threading.Thread(target=runner, daemon=True).start()
    return loop


def run_coro(coro):
    loop = ensure_loop()
    return asyncio.run_coroutine_threadsafe(coro, loop)


async def start_capture(url: str) -> None:
    try:
        from playwright.async_api import async_playwright
    except ImportError:
        STATE.log("缺少 playwright，请先运行 requirements 安装。", "error")
        return

    if not STATE.browser_path:
        STATE.log("没有找到 Edge/Chrome 浏览器。", "error")
        return

    PROFILE_DIR.mkdir(parents=True, exist_ok=True)
    DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)
    target_url = url.strip() or DEFAULT_LOGIN_URL

    if STATE.context is None:
        STATE.playwright = await async_playwright().start()
        STATE.context = await STATE.playwright.chromium.launch_persistent_context(
            user_data_dir=str(PROFILE_DIR),
            executable_path=STATE.browser_path,
            headless=False,
            viewport={"width": 1280, "height": 900},
            args=["--disable-blink-features=AutomationControlled", "--autoplay-policy=no-user-gesture-required"],
        )
        STATE.context.on("page", attach_page)
        for page in STATE.context.pages:
            attach_page(page)
        STATE.page = STATE.context.pages[0] if STATE.context.pages else await STATE.context.new_page()
        attach_page(STATE.page)

    with STATE.lock:
        STATE.capture_running = True
        STATE.capture_url = target_url
    STATE.log("Edge 捕获窗口已启动。请登录、进入已购课节并开始播放。")
    await STATE.page.goto(target_url, wait_until="domcontentloaded")


def attach_page(page) -> None:
    try:
        page.on("response", lambda response: asyncio.create_task(remember_response(response)))
    except Exception:
        pass


async def remember_response(response) -> None:
    url = response.url
    lower = url.lower()
    if any(hint in lower for hint in DRM_HINTS):
        with STATE.lock:
            STATE.drm_hits.append(url)
    try:
        headers = await response.request.all_headers()
    except Exception:
        headers = {}
    content_type = response.headers.get("content-type", "")
    kind = guess_kind(url, content_type)
    if not kind:
        return
    cid = candidate_id(url)
    parsed = urlparse(url)
    title = ""
    try:
        title = await response.request.frame.page.title()
    except Exception:
        title = ""
    with STATE.lock:
        existing = STATE.candidates.get(cid)
        if existing:
            existing.hits += 1
            existing.page_title = title or existing.page_title
            return
        STATE.candidates[cid] = MediaCandidate(
            id=cid,
            url=url,
            kind=kind,
            host=parsed.netloc,
            page_title=title,
            headers=headers,
            content_type=content_type,
        )
    STATE.log(f"捕获到 {kind}：{parsed.netloc}")


async def stop_capture() -> None:
    if STATE.context:
        await STATE.context.close()
    if STATE.playwright:
        await STATE.playwright.stop()
    STATE.context = None
    STATE.playwright = None
    STATE.page = None
    with STATE.lock:
        STATE.capture_running = False
    STATE.log("捕获窗口已关闭。")


async def download_candidate(candidate: MediaCandidate, job: Job, media_type: str = "video") -> None:
    if not STATE.context:
        job.status = "failed"
        job.error = "浏览器会话不存在，请先启动捕获。"
        return
    if not STATE.ffmpeg_path:
        job.status = "failed"
        job.error = "没有找到 ffmpeg。"
        return

    DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)
    output_path = make_output_path(candidate, media_type)
    cookies = await STATE.context.cookies(candidate.url)
    headers = header_lines(candidate.headers, build_cookie_header(cookies))

    cmd = [
        STATE.ffmpeg_path,
        "-hide_banner",
        "-loglevel",
        "info",
        "-y",
        "-headers",
        headers,
        "-i",
        candidate.url,
    ]
    if candidate.kind == "m3u8":
        cmd[1:1] = ["-protocol_whitelist", "file,http,https,tcp,tls,crypto", "-allowed_extensions", "ALL"]
    if media_type == "audio":
        cmd.extend(["-vn", "-map", "0:a:0", "-c:a", "copy"])
    else:
        cmd.extend(["-c", "copy"])
    if candidate.kind == "m3u8":
        cmd.extend(["-bsf:a", "aac_adtstoasc"])
    cmd.append(str(output_path))

    job.status = "running"
    job.output = str(output_path)
    STATE.log(f"开始下载{'音频' if media_type == 'audio' else '视频'}：{output_path.name}")
    rc = await asyncio.to_thread(run_process_log, cmd, job.id)
    if rc == 0 and output_path.exists():
        job.status = "done"
        job.finished_at = time.time()
        job.progress = 1
        STATE.log(f"下载完成：{output_path.name}", "success")
    else:
        job.status = "failed"
        job.finished_at = time.time()
        job.error = f"ffmpeg 退出码 {rc}"
        STATE.log(f"下载失败：{job.error}", "error")


def run_process_log(cmd: List[str], job_id: str) -> int:
    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding=locale.getpreferredencoding(False),
        errors="replace",
    )
    for line in proc.stdout or []:
        line = line.strip()
        if line:
            STATE.log(line)
    return proc.wait()


def start_download(candidate_id_value: str, media_type: str = "video") -> Optional[str]:
    with STATE.lock:
        candidate = STATE.candidates.get(candidate_id_value)
        if not candidate:
            return None
        if media_type not in {"video", "audio"}:
            media_type = "video"
        job_id = f"download-{int(time.time() * 1000)}"
        label_prefix = "仅音频" if media_type == "audio" else "视频"
        job = Job(id=job_id, kind="download", label=f"{label_prefix} · {candidate.page_title or candidate.host}")
        STATE.jobs[job_id] = job
    run_coro(download_candidate(candidate, job, media_type))
    return job_id


def start_transcription(payload: dict) -> str:
    input_path = payload.get("path") or str(DOWNLOAD_DIR)
    model = payload.get("model") or "medium"
    language = payload.get("language") or "zh"
    device = payload.get("device") or "auto"
    force = bool(payload.get("force"))
    job_id = f"transcribe-{int(time.time() * 1000)}"
    job = Job(id=job_id, kind="transcribe", label=Path(input_path).name or "downloads")
    with STATE.lock:
        STATE.jobs[job_id] = job
    threading.Thread(target=run_transcription_job, args=(job, input_path, model, language, device, force), daemon=True).start()
    return job_id


def run_transcription_job(job: Job, input_path: str, model: str, language: str, device: str, force: bool) -> None:
    job.status = "running"
    TRANSCRIPT_DIR.mkdir(parents=True, exist_ok=True)
    model_path = MODELS_DIR / f"faster-whisper-{model}"

    try:
        gpu = gpu_status()
        if device == "auto" and not gpu["ready"]:
            device = "cpu"
            STATE.log("自动设备已切换为 CPU：当前 CUDA/cuDNN 运行库不完整。")

        if not (model_path / "model.bin").exists():
            STATE.log(f"模型 {model} 尚未下载，开始下载。")
            ps = ROOT / "download_faster_whisper_model.ps1"
            rc = run_process_log(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(ps), "-Model", model], job.id)
            if rc != 0:
                raise RuntimeError(f"模型下载失败，退出码 {rc}")

        cmd = [
            sys.executable,
            str(ROOT / "transcribe_local.py"),
            input_path,
            "--model",
            str(model_path),
            "--language",
            language,
            "--device",
            device,
            "--output",
            str(TRANSCRIPT_DIR),
        ]
        if force:
            cmd.append("--force")
        STATE.log(f"开始转写：{input_path}")
        rc = run_process_log(cmd, job.id)
        if rc != 0:
            raise RuntimeError(f"转写进程退出码 {rc}")
        job.status = "done"
        job.progress = 1
        job.finished_at = time.time()
        job.output = str(TRANSCRIPT_DIR)
        STATE.log("转写完成。", "success")
    except Exception as exc:
        job.status = "failed"
        job.error = str(exc)
        job.finished_at = time.time()
        STATE.log(f"转写失败：{exc}", "error")


class Handler(BaseHTTPRequestHandler):
    server_version = "XiaoeLocalUI/1.0"

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/api/state":
            self.send_json(STATE.snapshot())
            return
        if parsed.path.startswith("/open/"):
            self.open_path(unquote(parsed.path[len("/open/") :]))
            return
        self.serve_static(parsed.path)

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        payload = self.read_json()
        if parsed.path == "/api/capture/start":
            run_coro(start_capture(str(payload.get("url") or "")))
            self.send_json({"ok": True})
            return
        if parsed.path == "/api/capture/stop":
            run_coro(stop_capture())
            self.send_json({"ok": True})
            return
        if parsed.path == "/api/candidates/clear":
            with STATE.lock:
                STATE.candidates.clear()
            self.send_json({"ok": True})
            return
        if parsed.path == "/api/jobs/clear":
            with STATE.lock:
                STATE.jobs = {key: job for key, job in STATE.jobs.items() if job.status in {"queued", "running"}}
            self.send_json({"ok": True})
            return
        if parsed.path == "/api/logs/clear":
            with STATE.lock:
                STATE.logs.clear()
            self.send_json({"ok": True})
            return
        if parsed.path == "/api/download":
            job_id = start_download(str(payload.get("id") or ""), str(payload.get("type") or "video"))
            self.send_json({"ok": bool(job_id), "job_id": job_id})
            return
        if parsed.path == "/api/transcribe":
            self.send_json({"ok": True, "job_id": start_transcription(payload)})
            return
        self.send_error(404)

    def read_json(self) -> dict:
        length = int(self.headers.get("Content-Length", "0") or "0")
        if not length:
            return {}
        raw = self.rfile.read(length)
        try:
            return json.loads(raw.decode("utf-8"))
        except json.JSONDecodeError:
            return {}

    def send_json(self, data: dict) -> None:
        raw = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def serve_static(self, request_path: str) -> None:
        rel = "index.html" if request_path in {"", "/"} else request_path.lstrip("/")
        target = (STATIC_DIR / rel).resolve()
        if not str(target).startswith(str(STATIC_DIR.resolve())) or not target.exists() or target.is_dir():
            self.send_error(404)
            return
        raw = target.read_bytes()
        content_type = mimetypes.guess_type(str(target))[0] or "application/octet-stream"
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def open_path(self, raw_path: str) -> None:
        path = Path(raw_path)
        if path.exists():
            os.startfile(str(path if path.is_dir() else path.parent))
            self.send_json({"ok": True})
        else:
            self.send_json({"ok": False})

    def log_message(self, format: str, *args) -> None:
        return


def main() -> int:
    add_nvidia_runtime_to_path()
    DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)
    TRANSCRIPT_DIR.mkdir(parents=True, exist_ok=True)
    host = "127.0.0.1"
    port = int(os.environ.get("XIAOE_UI_PORT", "8765"))
    STATE.log(f"Web UI 启动：http://{host}:{port}")
    server = ThreadingHTTPServer((host, port), Handler)
    if "--no-browser" not in sys.argv:
        threading.Timer(0.8, lambda: webbrowser.open(f"http://{host}:{port}")).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
