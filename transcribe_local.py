#!/usr/bin/env python3
"""Local faster-whisper transcription for downloaded course videos."""

from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
import tempfile
import site
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, List, Optional, Sequence


MEDIA_SUFFIXES = {
    ".mp4",
    ".mkv",
    ".mov",
    ".avi",
    ".flv",
    ".webm",
    ".m4v",
    ".mp3",
    ".m4a",
    ".aac",
    ".wav",
    ".flac",
    ".ogg",
}

NVIDIA_DLL_SUBDIRS = (
    Path("nvidia") / "cublas" / "bin",
    Path("nvidia") / "cudnn" / "bin",
    Path("nvidia") / "cuda_nvrtc" / "bin",
)


@dataclass
class TranscriptSegment:
    start: float
    end: float
    text: str


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

    return shutil.which("ffmpeg")


def sanitize_filename(value: str, fallback: str = "transcript") -> str:
    value = re.sub(r"[\\/:*?\"<>|]+", "_", value or "")
    value = re.sub(r"\s+", " ", value).strip(" .")
    return value[:140] or fallback


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
    dirs = nvidia_runtime_dirs()
    if not dirs:
        return
    current_path = os.environ.get("PATH", "")
    current_parts = {part.lower() for part in current_path.split(os.pathsep) if part}
    prepend = []
    for path in dirs:
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


def collect_inputs(paths: Sequence[str]) -> List[Path]:
    files: List[Path] = []
    for raw in paths:
        path = Path(raw).expanduser().resolve()
        if path.is_dir():
            for item in path.rglob("*"):
                if item.is_file() and item.suffix.lower() in MEDIA_SUFFIXES:
                    files.append(item)
        elif path.is_file():
            files.append(path)
        else:
            print(f"Skipping missing path: {path}")
    deduped = []
    seen = set()
    for item in files:
        key = str(item).lower()
        if key not in seen:
            deduped.append(item)
            seen.add(key)
    return deduped


def extract_audio(ffmpeg: str, source: Path, temp_dir: Path) -> Path:
    audio_path = temp_dir / (sanitize_filename(source.stem) + ".wav")
    cmd = [
        ffmpeg,
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-i",
        str(source),
        "-vn",
        "-ac",
        "1",
        "-ar",
        "16000",
        "-c:a",
        "pcm_s16le",
        str(audio_path),
    ]
    subprocess.run(cmd, check=True)
    return audio_path


def write_plain_txt(path: Path, segments: Iterable[TranscriptSegment]) -> None:
    pieces = [segment.text.strip() for segment in segments if segment.text.strip()]
    with path.open("w", encoding="utf-8") as handle:
        handle.write("\n\n".join(pieces))
        handle.write("\n")


def has_windows_dll(name: str) -> bool:
    found = shutil.which(name)
    if found:
        return True
    for directory in nvidia_runtime_dirs():
        if (directory / name).exists():
            return True
    if os.name != "nt":
        return False
    try:
        result = subprocess.run(["where.exe", name], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
    except Exception:
        return False
    return result.returncode == 0


def cuda_runtime_ready() -> bool:
    try:
        nvidia = subprocess.run(["nvidia-smi"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False).returncode == 0
    except Exception:
        nvidia = False
    if not nvidia:
        return False
    cublas = has_windows_dll("cublas64_12.dll")
    cudnn = has_windows_dll("cudnn_ops64_9.dll") or has_windows_dll("cudnn64_9.dll")
    return cublas and cudnn


def select_device(requested: str) -> str:
    if requested != "auto":
        return requested
    if cuda_runtime_ready():
        return "cuda"
    print("CUDA runtime is not ready; using CPU for stability.")
    return "cpu"


def compute_type_for(device: str, requested: str) -> str:
    if requested != "auto":
        return requested
    return "float16" if device == "cuda" else "int8"


def load_model(model_name: str, device: str, compute_type: str):
    from faster_whisper import WhisperModel

    attempts = [(device, compute_type)]
    if device == "cuda":
        attempts.extend([("cuda", "int8_float16"), ("cpu", "int8")])
    elif device != "cpu":
        attempts.append(("cpu", "int8"))

    last_error: Optional[Exception] = None
    for attempt_device, attempt_compute in attempts:
        try:
            print(f"Loading model: {model_name} on {attempt_device} ({attempt_compute})")
            return WhisperModel(model_name, device=attempt_device, compute_type=attempt_compute)
        except Exception as exc:
            last_error = exc
            print(f"Model load failed on {attempt_device} ({attempt_compute}): {exc}")
    raise RuntimeError(f"Unable to load faster-whisper model: {last_error}")


def is_cuda_runtime_error(error: Exception) -> bool:
    text = str(error).lower()
    needles = [
        "cublas",
        "cudnn",
        "cuda",
        "cannot be loaded",
        "is not found",
        "not found or cannot be loaded",
    ]
    return any(needle in text for needle in needles)


def transcribe_file(model, source: Path, output_dir: Path, ffmpeg: str, args: argparse.Namespace) -> None:
    output_stem = sanitize_filename(source.stem)
    target_dir = output_dir / output_stem if args.separate_dirs else output_dir
    target_dir.mkdir(parents=True, exist_ok=True)

    plain_txt = target_dir / f"{output_stem}.txt"

    if plain_txt.exists() and not args.force:
        print(f"Skipping existing transcript: {plain_txt}")
        return

    with tempfile.TemporaryDirectory(prefix="xiaoe_transcribe_") as temp:
        temp_dir = Path(temp)
        print(f"\nExtracting audio: {source.name}")
        audio_path = extract_audio(ffmpeg, source, temp_dir)

        print("Transcribing...")
        segments_iter, _info = model.transcribe(
            str(audio_path),
            language=args.language or None,
            vad_filter=True,
            vad_parameters={"min_silence_duration_ms": args.min_silence_ms},
            beam_size=args.beam_size,
            initial_prompt=args.initial_prompt or None,
        )

        segments = [
            TranscriptSegment(float(segment.start), float(segment.end), segment.text)
            for segment in segments_iter
        ]

    write_plain_txt(plain_txt, segments)

    print(f"Saved: {plain_txt}")


def parse_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Transcribe local course videos with faster-whisper.")
    parser.add_argument("inputs", nargs="+", help="Video/audio file or directory. Directories are scanned recursively.")
    parser.add_argument("--output", default="transcripts", help="Output directory. Default: transcripts")
    parser.add_argument("--model", default="medium", help="Whisper model. Suggested: small, medium, large-v3")
    parser.add_argument("--language", default="zh", help="Language code. Use zh for Chinese, or empty string for auto.")
    parser.add_argument("--device", choices=["auto", "cuda", "cpu"], default="auto")
    parser.add_argument("--compute-type", default="auto", help="auto, float16, int8_float16, int8, etc.")
    parser.add_argument("--ffmpeg", help="Path to ffmpeg.exe")
    parser.add_argument("--beam-size", type=int, default=5)
    parser.add_argument("--min-silence-ms", type=int, default=500)
    parser.add_argument("--initial-prompt", default="", help="Optional glossary/context prompt for names and terms.")
    parser.add_argument("--separate-dirs", action="store_true", help="Put each video's outputs in its own folder.")
    parser.add_argument("--force", action="store_true", help="Overwrite existing transcripts.")
    return parser.parse_args(argv)


def main(argv: Sequence[str]) -> int:
    args = parse_args(argv)
    add_nvidia_runtime_to_path()

    ffmpeg = args.ffmpeg or default_ffmpeg_path()
    if not ffmpeg or not Path(ffmpeg).exists():
        print("ffmpeg was not found. Pass --ffmpeg C:\\path\\to\\ffmpeg.exe")
        return 2

    files = collect_inputs(args.inputs)
    if not files:
        print("No media files found.")
        return 2

    output_dir = Path(args.output).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    try:
        import faster_whisper  # noqa: F401
    except ImportError:
        print("Missing dependency: faster-whisper")
        print("Run: python -m pip install -r requirements-transcribe.txt")
        return 2

    device = select_device(args.device)
    compute_type = compute_type_for(device, args.compute_type)
    model = load_model(args.model, device, compute_type)
    cpu_model = None

    print(f"Found {len(files)} media file(s).")
    failures = 0
    for file_path in files:
        try:
            transcribe_file(model, file_path, output_dir, ffmpeg, args)
        except subprocess.CalledProcessError as exc:
            print(f"ffmpeg failed for {file_path}: {exc}")
            failures += 1
        except Exception as exc:
            if device == "cuda" and is_cuda_runtime_error(exc):
                print(f"CUDA transcription failed for {file_path}: {exc}")
                print("Retrying this file on CPU (int8). GPU acceleration needs CUDA/cuDNN runtime DLLs.")
                try:
                    if cpu_model is None:
                        cpu_model = load_model(args.model, "cpu", "int8")
                    transcribe_file(cpu_model, file_path, output_dir, ffmpeg, args)
                    continue
                except Exception as retry_exc:
                    print(f"CPU retry failed for {file_path}: {retry_exc}")
            else:
                print(f"Transcription failed for {file_path}: {exc}")
            failures += 1

    print("\nAll done.")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
