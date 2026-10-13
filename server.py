from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "work" / "media"
OUT = ROOT / "outputs"
PROJECTS_FILE = ROOT / "work" / "projects.json"
PACKAGES = ROOT / "work" / "python-packages"
LOCAL_PACKAGES = ROOT / "work" / "runtime-packages-v5"
LEGACY_PACKAGES = ROOT / "work" / "runtime-packages-v2"
if LOCAL_PACKAGES.is_dir():
    sys.path.insert(0, str(LOCAL_PACKAGES))
sys.path.insert(1 if LOCAL_PACKAGES.is_dir() else 0, str(PACKAGES))
os.environ["APPDATA"] = str(ROOT / "work" / "appdata")
os.environ["LOCALAPPDATA"] = str(ROOT / "work" / "localappdata")
DATA.mkdir(parents=True, exist_ok=True)
OUT.mkdir(parents=True, exist_ok=True)
try:
    _saved_projects = json.loads(PROJECTS_FILE.read_text(encoding="utf-8-sig")) if PROJECTS_FILE.exists() else []
except Exception:
    _saved_projects = []
JOBS: dict[str, dict] = {item["id"]: item for item in _saved_projects if isinstance(item, dict) and item.get("id")}
# Import outputs made by earlier app versions so existing clips appear in the new history.
if not _saved_projects:
    legacy = {}
    for video in OUT.glob("*_klip_*.mp4"):
        match = re.match(r"(?P<prefix>[a-f0-9]{8})_klip_(?P<num>\d+)\.mp4$", video.name, re.I)
        if not match:
            continue
        group = legacy.setdefault(match["prefix"], {"clips": [], "createdAt": video.stat().st_mtime})
        subtitle = video.with_suffix(".srt")
        group["clips"].append({"name": video.name, "url": "/outputs/" + video.name, "start": 0, "end": 0, **({"subtitle": "/outputs/" + subtitle.name} if subtitle.exists() else {})})
        group["createdAt"] = max(group["createdAt"], video.stat().st_mtime)
    for prefix, item in legacy.items():
        job_id = "legacy-" + prefix
        JOBS[job_id] = {"id": job_id, "status": "complete", "progress": 100, "message": "Önceki sürümden aktarıldı", "title": "Önceki video projesi · " + prefix, **item}
LOCK = threading.Lock()


def persist_project(job_id: str):
    with LOCK:
        job = dict(JOBS.get(job_id, {}))
        if not job:
            return
        rows = [item for item in JOBS.values() if item.get("status") in ("complete", "error")]
        rows.sort(key=lambda item: item.get("createdAt", 0), reverse=True)
        rows = rows[:100]
        temp = PROJECTS_FILE.with_suffix(".tmp")
        temp.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
        temp.replace(PROJECTS_FILE)


def has_module(name: str) -> bool:
    try:
        if name == "faster_whisper":
            from faster_whisper import WhisperModel  # noqa: F401
        else:
            __import__(name)
        return True
    except Exception:
        return False


def load_whisper_model(model_name: str, download_root: str):
    """Bridge older faster-whisper releases to PyAV 19, which removed metadata_errors."""
    import av
    original_open = av.open
    if not getattr(original_open, "_clipatolye_compat", False):
        def compatible_open(*args, **kwargs):
            kwargs.pop("metadata_errors", None)
            return original_open(*args, **kwargs)
        compatible_open._clipatolye_compat = True
        av.open = compatible_open
    from faster_whisper import WhisperModel
    return WhisperModel(model_name, device="cpu", compute_type="int8", download_root=download_root)


def has_yt_dlp() -> bool:
    try:
        from yt_dlp import YoutubeDL  # noqa: F401
        return True
    except Exception:
        # Keep the older, readable yt-dlp install off sys.path during
        # faster-whisper imports: pkg_resources scans every distribution path.
        sys.modules.pop("yt_dlp", None)
        if not LEGACY_PACKAGES.is_dir():
            return False
        sys.path.insert(0, str(LEGACY_PACKAGES))
        try:
            from yt_dlp import YoutubeDL  # noqa: F401
            return True
        except Exception:
            return False
        finally:
            try: sys.path.remove(str(LEGACY_PACKAGES))
            except ValueError: pass


def tools_status():
    ffmpeg, ffprobe = media_binary("ffmpeg"), media_binary("ffprobe")
    return {"ffmpeg": ffmpeg is not None, "ffprobe": ffprobe is not None,
            "yt_dlp": shutil.which("yt-dlp") is not None or has_yt_dlp(),
            "whisper": has_module("faster_whisper")}


def media_binary(name: str):
    found = shutil.which(name)
    if found: return found
    binary = name + (".exe" if os.name == "nt" else "")
    local_bins = [ROOT / "work" / "tools" / "ffmpeg" / "bin" / binary,
                  ROOT / "work" / "tools-v2" / "ffmpeg" / "bin" / binary,
                  ROOT / "work" / "tools" / "bin" / binary,
                  Path(os.environ.get("LOCALAPPDATA", str(ROOT / "work" / "localappdata"))) / "ffmpegio" / "ffmpeg-downloader" / "ffmpeg" / "bin" / binary]
    for candidate in local_bins:
        try:
            if candidate.is_file(): return str(candidate)
        except OSError:
            pass
    try:
        import ffmpeg_downloader as ffdl
        import ffmpeg_downloader._backend as backend
        import ffmpeg_downloader._config as config_module
        import ffmpeg_downloader._path as path_module
        local_tools = ROOT / "work" / "tools"
        local_cache = local_tools / "cache"
        backend.get_dir = lambda: str(local_tools)
        backend.cache_dir = lambda: str(local_cache)
        config_module.get_dir = lambda: str(local_tools)
        path_module.get_dir = lambda: str(local_tools)
        path_module.get_cache_dir = lambda: str(local_cache)
        path_module.get_installed_dir = lambda: str(local_tools / "ffmpeg")
        p = ffdl.ffmpeg_path if name == "ffmpeg" else ffdl.ffprobe_path
        return p if p and Path(p).is_file() else None
    except Exception:
        return None


def normalize_video_url(value: str) -> str:
    """Accept both plain URLs and Markdown links copied from chat."""
    value = (value or "").strip()
    match = re.fullmatch(r"\[([^\]]+)\]\((https?://[^)]+)\)", value)
    if match:
        value = match.group(2).strip()
    return value


def yt_dlp_info(url: str, *, download: bool = False, output: Path | None = None, quality: int = 1080):
    # Run yt-dlp through its Python API so it uses this app's bundled package
    # directory; spawning `python -m yt_dlp` loses that local import path.
    from yt_dlp import YoutubeDL
    options = {"quiet": True, "no_warnings": True, "noplaylist": True, "ignoreerrors": False}
    if not download:
        options["skip_download"] = True
    else:
        options.update({"format": f"bv*[height<={quality}]+ba/b[height<={quality}]/b",
                        "merge_output_format": "mp4", "outtmpl": str(output), "overwrites": True})
        ffmpeg_path = media_binary("ffmpeg")
        if ffmpeg_path:
            options["ffmpeg_location"] = str(Path(ffmpeg_path).parent)
    try:
        with YoutubeDL(options) as ydl:
            if download:
                ydl.download([url])
                return None
            return ydl.extract_info(url, download=False)
    except Exception as exc:
        detail = str(exc).strip() or exc.__class__.__name__
        detail = re.sub(r"\x1b\[[0-?]*[ -/]*[@-~]", "", detail)
        if "403" in detail or "Forbidden" in detail:
            raise ValueError("YouTube video akışını 403 ile engelledi. Bu videoyu cihazına indirip ‘Video dosyası’ sekmesinden yükleyerek işleyebilirsin. Bazı yaş, üyelik veya YouTube doğrulaması isteyen videolar bağlantıdan alınamayabilir.") from exc
        raise ValueError(f"Video kaynağı okunamadı: {detail}") from exc


def get_remote_info(url: str):
    url = normalize_video_url(url)
    parsed = urlparse(url)
    if parsed.scheme not in ("https", "http") or not parsed.hostname or parsed.hostname in ("localhost", "127.0.0.1", "::1"):
        raise ValueError("Geçerli bir herkese açık video bağlantısı gir.")
    info = yt_dlp_info(url)
    return {"title": info.get("title", "Video"), "duration": info.get("duration"), "width": info.get("width"), "height": info.get("height"),
            "filesize": info.get("filesize") or info.get("filesize_approx"), "extractor": info.get("extractor_key"), "thumbnail": info.get("thumbnail")}


def format_srt_time(seconds: float):
    ms = max(0, round(seconds * 1000)); h, ms = divmod(ms, 3600000); m, ms = divmod(ms, 60000); s, ms = divmod(ms, 1000)
    return f"{h:02}:{m:02}:{s:02},{ms:03}"


def subtitle_file(words: list, start: float, end: float, path: Path):
    selected = [w for w in words if w["start"] >= start and w["end"] <= end]
    rows, group = [], []
    for word in selected:
        group.append(word)
        if len(group) >= 5 or word["word"].strip().endswith(('.', '?', '!', ',')):
            rows.append(group); group = []
    if group: rows.append(group)
    content = []
    for i, row in enumerate(rows, 1):
        content += [str(i), f"{format_srt_time(row[0]['start']-start)} --> {format_srt_time(row[-1]['end']-start)}", " ".join(w["word"].strip() for w in row), ""]
    path.write_text("\n".join(content), encoding="utf-8-sig")


def loop_timeline_words(words: list, start: float, end: float, seconds: float):
    """Shift subtitle cues to the looped timeline; the first/last half seam is blended."""
    length = end - start
    mapped = []
    if seconds <= 0 or length <= seconds * 2.2:
        return mapped
    # The seam starts with the midpoint of the tail/head crossfade and ends
    # at that same midpoint. This rotates the timeline by half the seam length.
    visible_start, visible_end = seconds / 2, length - seconds / 2
    for word in words:
        ws = max(visible_start, word["start"] - start)
        we = min(visible_end, word["end"] - start)
        new_start, new_end = ws - visible_start, we - visible_start
        if new_end > new_start:
            mapped.append({"start": new_start, "end": new_end, "word": word["word"]})
    return sorted(mapped, key=lambda word: word["start"])


def make_loop_video(ffmpeg: str, path: Path, length: float, seconds: float, has_audio: bool):
    if seconds <= 0 or length <= seconds * 2.2:
        return length, False
    temp = path.with_name(path.stem + "_loop_tmp.mp4")
    half = seconds / 2
    middle_start, middle_end = seconds, length - seconds
    graph = (
        f"[0:v]split=3[tailSrc][headSrc][middleSrc];"
        f"[tailSrc]trim=start={middle_end}:end={length},setpts=PTS-STARTPTS,fps=30,settb=AVTB,format=yuv420p[tail];"
        f"[headSrc]trim=start=0:end={seconds},setpts=PTS-STARTPTS,fps=30,settb=AVTB,format=yuv420p[head];"
        f"[tail][head]xfade=transition=fade:duration={seconds}:offset=0,split=2[seamA][seamB];"
        f"[seamA]trim=start={half}:end={seconds},setpts=PTS-STARTPTS[vstart];"
        f"[seamB]trim=start=0:end={half},setpts=PTS-STARTPTS[vend];"
        f"[middleSrc]trim=start={middle_start}:end={middle_end},setpts=PTS-STARTPTS,fps=30,settb=AVTB,format=yuv420p[middle];"
        f"[vstart][middle][vend]concat=n=3:v=1:a=0[vout]"
    )
    if has_audio:
        graph += (
            ";[0:a]asplit=3[atailSrc][aheadSrc][amidSrc];"
            f"[atailSrc]atrim=start={middle_end}:end={length},asetpts=PTS-STARTPTS[atail];"
            f"[aheadSrc]atrim=start=0:end={seconds},asetpts=PTS-STARTPTS[ahead];"
            f"[atail][ahead]acrossfade=d={seconds}:c1=tri:c2=tri,asplit=2[aseamA][aseamB];"
            f"[aseamA]atrim=start={half}:end={seconds},asetpts=PTS-STARTPTS[astart];"
            f"[aseamB]atrim=start=0:end={half},asetpts=PTS-STARTPTS[aend];"
            f"[amidSrc]atrim=start={middle_start}:end={middle_end},asetpts=PTS-STARTPTS[amid];"
            "[astart][amid][aend]concat=n=3:v=0:a=1[aout]"
        )
    cmd = [ffmpeg, "-y", "-i", str(path), "-filter_complex", graph, "-map", "[vout]"]
    if has_audio:
        cmd += ["-map", "[aout]"]
    cmd += ["-c:v", "libx264", "-preset", "veryfast", "-crf", "22"]
    if has_audio:
        cmd += ["-c:a", "aac"]
    cmd += ["-movflags", "+faststart", str(temp)]
    try:
        subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, timeout=1800)
        os.replace(temp, path)
        return length - seconds, True
    except subprocess.CalledProcessError as exc:
        temp.unlink(missing_ok=True)
        detail = exc.stderr.decode("utf-8", "replace")[-1800:] if exc.stderr else ""
        raise ValueError("Döngü geçişi oluşturulamadı: " + detail)


def rank_moments(words: list, duration: float, count: int, clip_length: int):
    terms = ("aslında", "çünkü", "ama", "sır", "hata", "başarı", "inanılmaz", "şaşırtıcı", "ücretsiz", "keşke", "dikkat", "önemli", "neden", "nasıl", "sonuç", "risk", "gerçek", "öğrendim", "değişti", "never", "secret", "mistake", "because", "surprising", "important", "free")
    max_start = max(0, duration - clip_length)
    candidates = []
    step = max(5, clip_length // 5)
    for sec in range(0, int(max_start) + 1, step):
        chunk = [w for w in words if sec <= w["start"] < sec + clip_length]
        if not chunk: continue
        text = " ".join(w["word"].lower() for w in chunk)
        density = len(chunk) / max(1, clip_length)
        signal = sum(1 for t in terms if t in text)
        punctuation = sum(1 for w in chunk if any(c in w["word"] for c in "?!"))
        score = min(100, round(42 + density * 100 + signal * 3 + punctuation * 2))
        candidates.append({"start": float(sec), "end": min(duration, float(sec + clip_length)), "score": score, "quote": text[:130]})
    chosen = []
    for c in sorted(candidates, key=lambda x: x["score"], reverse=True):
        if all(abs(c["start"] - p["start"]) >= clip_length * .8 for p in chosen): chosen.append(c)
        if len(chosen) == count: break
    if len(chosen) < count:
        for i in range(count):
            s = max_start * (i + .5) / count
            if all(abs(s-p["start"]) >= clip_length * .65 for p in chosen): chosen.append({"start": s, "end": min(duration, s+clip_length), "score": 50, "quote": ""})
            if len(chosen) == count: break
    return sorted(chosen[:count], key=lambda x: x["start"])


def probe(path: Path):
    ffprobe = media_binary("ffprobe")
    if not ffprobe:
        return None
    try:
        raw = subprocess.check_output([ffprobe, "-v", "quiet", "-print_format", "json", "-show_format", "-show_streams", str(path)], timeout=30)
        d = json.loads(raw)
        video = next((s for s in d.get("streams", []) if s.get("codec_type") == "video"), None)
        return {"duration": float(d.get("format", {}).get("duration", 0)), "size": path.stat().st_size,
                "width": video.get("width") if video else None, "height": video.get("height") if video else None, "hasVideo": video is not None, "hasAudio": any(s.get("codec_type") == "audio" for s in d.get("streams", []))}
    except Exception:
        return None


def run_job(job_id: str, config: dict):
    def update(**kw):
        with LOCK:
            JOBS[job_id].update(kw)
            finished = kw.get("status") in ("complete", "error")
        if finished:
            persist_project(job_id)
    try:
        update(status="processing", progress=8, message="Kaynak hazırlanıyor…")
        missing_tools = [name for name in ("ffmpeg", "ffprobe") if not media_binary(name)]
        if missing_tools:
            raise ValueError(f"Video işlemek için {', '.join(missing_tools)} bulunamadı. Başlat.bat'ı yeniden açıp FFmpeg kurulumunu tamamlayın.")
        source = config.get("source")
        src = Path(source) if source else None
        url = normalize_video_url(config.get("url") or "")
        if url:
            if not (shutil.which("yt-dlp") or has_yt_dlp()):
                raise ValueError("Video bağlantısını indirmek için yt-dlp kurulu değil.")
            remote = get_remote_info(url)
            update(message=f"“{remote['title']}” indiriliyor · {remote.get('duration') and int(remote['duration']//60)} dk", progress=14, media=remote, title=remote["title"])
            target = DATA / (job_id + ".%(ext)s")
            yt_dlp_info(url, download=True, output=target, quality=int(config.get("quality", 1080)))
            candidates = list(DATA.glob(job_id + ".*")); src = candidates[0] if candidates else None
        if not src or not src.exists():
            raise ValueError("Video dosyası bulunamadı.")
        details = probe(src)
        duration = details["duration"] if details and details["duration"] else float(config.get("duration", 0))
        if duration <= 0:
            raise ValueError("Video süresi okunamadı. ffmpeg ve ffprobe kurulu olmalı.")
        ffmpeg = media_binary("ffmpeg")
        if not ffmpeg:
            raise ValueError("Klip oluşturmak için ffmpeg kurulu değil.")
        update(message=f"Video inceleniyor · {duration/60:.1f} dakika", progress=24, duration=duration, title=JOBS[job_id].get("title") or src.stem, media={**(details or {}), "duration": duration})
        words = []
        if has_module("faster_whisper") and config.get("captions") != "off":
            update(message="Konuşma yazıya dökülüyor · altyazı zamanları eşleniyor…", progress=29)
            model = load_whisper_model("base", download_root=str(ROOT / "work" / "models"))
            segments, _ = model.transcribe(str(src), language=None if config.get("language") in (None, "auto", "other") else config.get("language"), word_timestamps=True, vad_filter=False)
            for segment in segments:
                for word in (segment.words or []):
                    words.append({"start": float(word.start), "end": float(word.end), "word": word.word})
            update(message=f"Döküm tamamlandı · {len(words)} kelime · güçlü anlar sıralanıyor…", progress=35, transcriptWords=len(words))
        moments = []
        if config.get("splitMode") == "range":
            start, end = max(0, float(config.get("start", 0))), min(duration, float(config.get("end", duration)))
            if end <= start: raise ValueError("Bitiş zamanı başlangıçtan sonra olmalı.")
            intervals = [(start, end)]
        else:
            count = max(1, min(30, int(config.get("count", 5))))
            length = max(5, min(180, int(config.get("clipLength", 45))))
            if config.get("splitMode") == "equal":
                intervals = [(duration*i/count, duration*(i+1)/count) for i in range(count)]
            elif words:
                moments = rank_moments(words, duration, count, length)
                intervals = [(c["start"], c["end"]) for c in moments]
            else:
                # Spread candidate windows across the source; transcript based ranking is added when Whisper is installed.
                usable = max(1, duration - length)
                intervals = [(usable*(i+0.5)/count, min(duration, usable*(i+0.5)/count + length)) for i in range(count)]
        update(message="Klipler hazırlanıyor…", progress=35)
        result_paths = []
        fmt = config.get("format", "9:16")
        vf = {"9:16": "scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920", "1:1": "scale=1080:1080:force_original_aspect_ratio=increase,crop=1080:1080", "16:9": "scale=1920:1080:force_original_aspect_ratio=increase,crop=1920:1080"}.get(fmt, "scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920")
        font_family = config.get("fontFamily", "Arial")
        if font_family not in ("Arial", "Tahoma", "Impact", "Georgia"):
            font_family = "Arial"
        font_files = {"Arial": "arial.ttf", "Tahoma": "tahoma.ttf", "Impact": "impact.ttf", "Georgia": "georgia.ttf"}
        caption_alignment = 8 if config.get("captionPosition") == "top" else 2
        caption_margin = 130 if caption_alignment == 8 else 100
        caption_style = f"FontName={font_family},FontSize=18,Outline=2,Shadow=1,MarginV={caption_margin},Alignment={caption_alignment}"
        for i, (start, end) in enumerate(intervals, 1):
            output = OUT / f"{job_id[:8]}_klip_{i:02}.mp4"
            srt = OUT / f"{job_id[:8]}_klip_{i:02}.srt"
            if words and config.get("captions") != "off": subtitle_file(words, start, end, srt)
            video_filter = vf
            filter_complex = None
            background_path = Path(config.get("background", "")) if config.get("background") else None
            fill_mode = config.get("fillMode", "crop")
            if fmt == "9:16" and fill_mode in ("blur", "background") and details and details.get("hasVideo"):
                fg = "[0:v]scale=1080:1920:force_original_aspect_ratio=decrease[fg]"
                if fill_mode == "blur":
                    filter_complex = "[0:v]split=2[bg0][fg0];[bg0]scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,boxblur=28:12,eq=brightness=-0.18[bg];[fg0]scale=1080:1920:force_original_aspect_ratio=decrease[fg];[bg][fg]overlay=(W-w)/2:(H-h)/2,setsar=1[base]"
                elif background_path and background_path.is_file() and DATA.resolve() in background_path.resolve().parents:
                    layout = config.get("backgroundLayout", "fill")
                    if layout in ("background_top", "video_top"):
                        bg_half = "[1:v]scale=1080:960:force_original_aspect_ratio=increase,crop=1080:960,setsar=1[bg]"
                        fg_half = "[0:v]scale=1080:960:force_original_aspect_ratio=decrease,pad=1080:960:(ow-iw)/2:(oh-ih)/2,setsar=1[fg]"
                        rows = "[bg][fg]vstack=inputs=2,setsar=1[base]" if layout == "background_top" else "[fg][bg]vstack=inputs=2,setsar=1[base]"
                        filter_complex = f"{bg_half};{fg_half};{rows}"
                    else:
                        filter_complex = f"[1:v]scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,setsar=1[bg];{fg};[bg][fg]overlay=(W-w)/2:(H-h)/2,setsar=1[base]"
                if filter_complex:
                    tail = "[base]"
                    if words and config.get("captions") == "burn" and srt.exists():
                        filter_complex += f";[base]subtitles=outputs/{srt.name}:force_style='{caption_style}'[captioned]"
                        tail = "[captioned]"
                    text = str(config.get("overlayText", "")).replace("\r", " ").replace("\n", " ").strip()
                    if text:
                        text_path = OUT / f"{job_id[:8]}_text.txt"
                        text_path.write_text(text, encoding="utf-8")
                        text_y = "h*0.08" if config.get("textPosition") != "bottom" else "h-text_h-h*0.12"
                        filter_complex += f";{tail}drawtext=font='{font_family}':textfile=outputs/{text_path.name}:fontcolor=white:fontsize=52:borderw=3:bordercolor=black:x=(w-text_w)/2:y={text_y}[vout]"
                    else:
                        filter_complex += f";{tail}null[vout]"
            if not filter_complex:
                if words and config.get("captions") == "burn" and srt.exists():
                    video_filter += f",subtitles=outputs/{srt.name}:force_style='{caption_style}'"
                text = str(config.get("overlayText", "")).replace("\r", " ").replace("\n", " ").strip()
                if text:
                    text_path = OUT / f"{job_id[:8]}_text.txt"
                    text_path.write_text(text, encoding="utf-8")
                    text_y = "h*0.08" if config.get("textPosition") != "bottom" else "h-text_h-h*0.12"
                    video_filter += f",drawtext=font='{font_family}':textfile=outputs/{text_path.name}:fontcolor=white:fontsize=52:borderw=3:bordercolor=black:x=(w-text_w)/2:y={text_y}"
            if details and not details.get("hasVideo"):
                cmd = [ffmpeg, "-y", "-f", "lavfi", "-i", "color=c=0x10100f:s=1080x1920:r=30", "-ss", str(start), "-i", str(src), "-t", str(end-start), "-vf", video_filter, "-c:v", "libx264", "-preset", "veryfast", "-crf", "22", "-c:a", "aac", "-shortest", "-movflags", "+faststart", str(output)]
            else:
                cmd = [ffmpeg, "-y", "-ss", str(start), "-i", str(src)]
                if filter_complex and fill_mode == "background" and background_path:
                    if background_path.suffix.lower() in (".mp4", ".mov", ".mkv", ".webm"):
                        cmd += ["-stream_loop", "-1", "-i", str(background_path)]
                    else:
                        cmd += ["-loop", "1", "-i", str(background_path)]
                cmd += ["-t", str(end-start)]
                if filter_complex:
                    cmd += ["-filter_complex", filter_complex, "-map", "[vout]", "-map", "0:a?"]
                else:
                    cmd += ["-vf", video_filter]
                cmd += ["-c:v", "libx264", "-preset", "veryfast", "-crf", "22", "-c:a", "aac", "-shortest", "-movflags", "+faststart", str(output)]
            try:
                subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, timeout=3600)
            except subprocess.CalledProcessError as exc:
                detail = exc.stderr.decode("utf-8", "replace")[-2400:] if exc.stderr else str(exc)
                raise ValueError("FFmpeg klibi oluşturamadı: " + detail) from exc
            loop_seconds = max(0.0, min(3.0, float(config.get("loopSeconds", 0) or 0)))
            looped_duration, looped = make_loop_video(ffmpeg, output, end - start, loop_seconds, bool(details and details.get("hasAudio"))) if loop_seconds else (end - start, False)
            if looped and words and config.get("captions") != "off" and srt.exists():
                subtitle_file(loop_timeline_words(words, start, end, loop_seconds), 0, looped_duration, srt)
            item = {"name": output.name, "url": "/outputs/" + output.name, "start": start, "end": end, "duration": looped_duration, "looped": looped}
            if moments and i <= len(moments): item.update(score=moments[i-1]["score"], reason=moments[i-1]["quote"])
            if srt.exists(): item["subtitle"] = "/outputs/" + srt.name
            result_paths.append(item)
            update(progress=35 + int(55 * i / len(intervals)), message=f"Klip {i}/{len(intervals)} dışa aktarılıyor…")
        update(status="complete", progress=100, message="Klipler hazır.", clips=result_paths,
               note=("Kesitler için tahmini öne çıkan anlar seçildi; transkript/altyazı üretimi için faster-whisper kurulu değil." if not words else "Öne çıkan kesitler konuşma dökümü sinyallerine göre sıralandı. Bu puan tahmindir; gerçek izlenme/retention analitiği değildir."))
    except Exception as e:
        update(status="error", progress=100, message=str(e), error=str(e))


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args): pass
    def send_json(self, data, code=200):
        body = json.dumps(data, ensure_ascii=False).encode()
        self.send_response(code); self.send_header("Content-Type", "application/json; charset=utf-8"); self.send_header("Content-Length", str(len(body))); self.send_header("Access-Control-Allow-Origin", "*"); self.end_headers(); self.wfile.write(body)
    def do_GET(self):
        p = urlparse(self.path).path
        if p == "/api/status": self.send_json({"version": 22, "tools": tools_status(), "outputDir": str(OUT)}); return
        if p == "/api/projects":
            with LOCK: projects = [dict(item) for item in JOBS.values()]
            projects.sort(key=lambda item: item.get("createdAt", 0), reverse=True)
            self.send_json(projects); return
        if p == "/api/inspect":
            try:
                if not (shutil.which("yt-dlp") or has_yt_dlp()): raise ValueError("yt-dlp paketi bu uygulamanın Python ortamında eksik veya bozuk. Uygulamanın kurulumunu yeniden çalıştırın.")
                self.send_json(get_remote_info(parse_qs(urlparse(self.path).query).get("url", [""])[0]))
            except Exception as e: self.send_json({"error":str(e)},400)
            return
        if p.startswith("/api/jobs/"):
            with LOCK: job = JOBS.get(p.rsplit("/", 1)[-1])
            self.send_json(job or {"error": "İş bulunamadı"}, 404 if job is None else 200); return
        if p.startswith("/outputs/"):
            path = (OUT / Path(unquote(p[len("/outputs/"):])).name)
            if path.exists():
                mime = "application/x-subrip; charset=utf-8" if path.suffix.lower() == ".srt" else "video/mp4"
                self.send_response(200); self.send_header("Content-Type", mime); self.send_header("Content-Length", str(path.stat().st_size)); self.end_headers()
                with path.open("rb") as f: shutil.copyfileobj(f, self.wfile)
            else: self.send_error(404)
            return
        path = ROOT / ("index.html" if p == "/" else p.lstrip("/"))
        if path.is_file() and ROOT in path.resolve().parents:
                data = path.read_bytes()
                if path.name == "index.html": data = data.replace(b"</body>", b'<script src="/extra.js"></script></body>')
                mime = "text/html; charset=utf-8" if path.suffix == ".html" else "text/javascript; charset=utf-8" if path.suffix == ".js" else "text/plain"
                self.send_response(200); self.send_header("Content-Type", mime); self.send_header("Content-Length", str(len(data))); self.end_headers(); self.wfile.write(data)
        else: self.send_error(404)
    def do_POST(self):
        p = urlparse(self.path).path
        if p.startswith("/api/outputs/"):
            name = Path(unquote(p[len("/api/outputs/"):])).name
            target = OUT / name
            size = int(self.headers.get("Content-Length", "0"))
            if target.suffix.lower() != ".srt" or not target.is_file() or size > 1024 * 1024:
                self.send_json({"error":"Altyazı dosyası bulunamadı veya boyutu geçersiz."},400); return
            try: target.write_text(self.rfile.read(size).decode("utf-8-sig"), encoding="utf-8-sig")
            except Exception as e: self.send_json({"error":str(e)},400); return
            self.send_json({"saved":True}); return
        if p == "/api/upload":
            name = unquote(self.headers.get("X-Filename", "video.mp4")); name = re.sub(r"[^\w. -]", "_", Path(name).name)
            path = DATA / f"{uuid.uuid4().hex}_{name}"
            remaining = int(self.headers.get("Content-Length", "0"))
            if remaining > 4 * 1024**3: self.send_json({"error":"Dosya en fazla 4 GB olabilir."}, 413); return
            with path.open("wb") as f:
                while remaining:
                    b = self.rfile.read(min(1024*1024, remaining));
                    if not b: break
                    f.write(b); remaining -= len(b)
            details = probe(path)
            self.send_json({"path":str(path),"name":name,"duration":details["duration"] if details else 0,"size":path.stat().st_size,"width":details["width"] if details else None,"height":details["height"] if details else None}); return
        if p == "/api/jobs":
            try: config = json.loads(self.rfile.read(int(self.headers.get("Content-Length", "0"))))
            except Exception: self.send_json({"error":"İstek okunamadı"},400); return
            job_id = uuid.uuid4().hex
            with LOCK: JOBS[job_id] = {"id":job_id,"status":"queued","progress":0,"message":"Sıraya alındı","createdAt":time.time(),"title":Path(config.get("source") or "Video projesi").stem,"settings":{k:config.get(k) for k in ("format","splitMode","count","clipLength","captions","loopSeconds")}}
            threading.Thread(target=run_job,args=(job_id,config),daemon=True).start()
            self.send_json({"id":job_id})
    def do_OPTIONS(self): self.send_response(204); self.send_header("Access-Control-Allow-Origin","*"); self.send_header("Access-Control-Allow-Headers","Content-Type,X-Filename"); self.send_header("Access-Control-Allow-Methods","GET,POST,OPTIONS"); self.end_headers()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8765")); print(f"ClipAtölye hazır: http://127.0.0.1:{port}")
    ThreadingHTTPServer(("127.0.0.1", port), Handler).serve_forever()
