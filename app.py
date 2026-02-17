import glob
import os
import threading
import uuid
from pathlib import Path
from urllib.parse import urlparse

from flask import Flask, after_this_request, jsonify, render_template, request, send_file
from yt_dlp import YoutubeDL
from yt_dlp.utils import DownloadError, sanitize_filename


# -----------------------------------------------------------------------------
# Flask app setup and core paths
# -----------------------------------------------------------------------------
BASE_DIR = Path(__file__).resolve().parent
DOWNLOAD_DIR = BASE_DIR / "downloads"

app = Flask(__name__, template_folder="templates", static_folder="static")
os.makedirs(DOWNLOAD_DIR, exist_ok=True)

# In-memory progress store:
# {
#   job_id: {
#     "status": "downloading|finished|error",
#     "percentage": int,
#     "message": str,
#     "file_path": str,
#     "file_name": str,
#     "job_prefix": str,
#   }
# }
PROGRESS_STORE: dict[str, dict] = {}
PROGRESS_LOCK = threading.Lock()


# -----------------------------------------------------------------------------
# Allowed platforms and shared helpers
# -----------------------------------------------------------------------------
SUPPORTED_DOMAINS = {
    "youtube.com",
    "www.youtube.com",
    "m.youtube.com",
    "youtu.be",
    "instagram.com",
    "www.instagram.com",
    "m.instagram.com",
}


def _error_response(message: str, status_code: int = 400):
    """Return a consistent JSON error response."""
    return jsonify({"error": message}), status_code


def _is_supported_media_url(url: str) -> bool:
    """Validate URL scheme + hostname for supported media providers."""
    try:
        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"}:
            return False
        return parsed.netloc.lower() in SUPPORTED_DOMAINS
    except Exception:
        return False


def _build_job_prefix(kind: str) -> str:
    """Build a unique filename prefix to avoid collisions per request."""
    return f"downly_{kind}_{uuid.uuid4().hex}"


def _find_downloaded_file(prefix: str, title: str, extension: str) -> Path | None:
    """
    Locate the final file using glob by title + extension.
    Falls back to prefix-only matching if title-based pattern misses.
    """
    safe_title = sanitize_filename(title or "", restricted=True)
    if safe_title:
        pattern = str(DOWNLOAD_DIR / f"{prefix}_{glob.escape(safe_title)}*.{extension}")
        matches = glob.glob(pattern)
        if matches:
            return Path(max(matches, key=os.path.getmtime))

    fallback_pattern = str(DOWNLOAD_DIR / f"{prefix}_*.{extension}")
    fallback_matches = glob.glob(fallback_pattern)
    if fallback_matches:
        return Path(max(fallback_matches, key=os.path.getmtime))
    return None


def _cleanup_job_files(prefix: str):
    """Delete all files for a specific job prefix (final + temp artifacts)."""
    for path in glob.glob(str(DOWNLOAD_DIR / f"{prefix}_*")):
        try:
            os.remove(path)
        except OSError:
            pass


def _run_ytdlp_download(url: str, ydl_opts: dict) -> dict:
    """Execute yt-dlp and return metadata dictionary."""
    with YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=True)
    return info


def _set_progress(job_id: str, **kwargs):
    """Thread-safe progress updates for one job."""
    with PROGRESS_LOCK:
        if job_id in PROGRESS_STORE:
            PROGRESS_STORE[job_id].update(kwargs)


def _create_job(job_id: str, job_prefix: str):
    """Initialize a new job in memory."""
    with PROGRESS_LOCK:
        PROGRESS_STORE[job_id] = {
            "status": "downloading",
            "percentage": 0,
            "message": "Starting download...",
            "file_path": "",
            "file_name": "",
            "job_prefix": job_prefix,
        }


def _get_job(job_id: str) -> dict | None:
    """Thread-safe read of one job state."""
    with PROGRESS_LOCK:
        job = PROGRESS_STORE.get(job_id)
        return dict(job) if job else None


def _delete_job(job_id: str):
    """Remove a job from memory."""
    with PROGRESS_LOCK:
        PROGRESS_STORE.pop(job_id, None)


def _download_worker(job_id: str, kind: str, url: str, job_prefix: str):
    """Run yt-dlp in a background thread and update progress hooks."""
    outtmpl = str(DOWNLOAD_DIR / f"{job_prefix}_%(title).200B.%(ext)s")
    _cleanup_job_files(job_prefix)

    def _progress_hook(data: dict):
        status = data.get("status")
        if status == "downloading":
            downloaded = data.get("downloaded_bytes") or 0
            total = data.get("total_bytes") or data.get("total_bytes_estimate") or 0
            percent = int((downloaded / total) * 100) if total else 0
            percent = max(0, min(percent, 99))
            _set_progress(
                job_id,
                status="downloading",
                percentage=percent,
                message=f"Processing... {percent}%",
            )
        elif status == "finished":
            # Download is complete; ffmpeg post-processing may still continue.
            _set_progress(job_id, status="downloading", percentage=99, message="Finalizing...")

    ydl_opts = {
        "outtmpl": outtmpl,
        "quiet": True,
        "noplaylist": True,
        "overwrites": True,
        "progress_hooks": [_progress_hook],
    }

    if kind == "video":
        ydl_opts.update(
            {
                "format": "bestvideo+bestaudio/best",
                "merge_output_format": "mp4",
            }
        )
        expected_ext = "mp4"
    else:
        ydl_opts.update(
            {
                "format": "bestaudio/best",
                "postprocessors": [
                    {
                        "key": "FFmpegExtractAudio",
                        "preferredcodec": "mp3",
                        "preferredquality": "192",
                    }
                ],
            }
        )
        expected_ext = "mp3"

    try:
        info = _run_ytdlp_download(url, ydl_opts)
        title = info.get("title", "") if isinstance(info, dict) else ""
        downloaded_path = _find_downloaded_file(job_prefix, title, expected_ext)
        if not downloaded_path:
            raise FileNotFoundError(f"Downloaded .{expected_ext} output not found.")

        _set_progress(
            job_id,
            status="finished",
            percentage=100,
            message="Download ready",
            file_path=str(downloaded_path),
            file_name=downloaded_path.name,
        )
    except DownloadError as exc:
        _set_progress(job_id, status="error", message=f"Download failed: {exc}")
        _cleanup_job_files(job_prefix)
    except Exception as exc:
        _set_progress(job_id, status="error", message=f"Unexpected server error: {exc}")
        _cleanup_job_files(job_prefix)


# -----------------------------------------------------------------------------
# Routes
# -----------------------------------------------------------------------------
@app.get("/")
def index():
    """Render the frontend page (GET-only to avoid POST / 405 issues)."""
    return render_template("index.html")


@app.post("/download/video")
def download_video():
    """Start an async video download job and return a job_id for polling."""
    url = request.form.get("url", "").strip()
    if not url:
        return _error_response("Missing required form field: url", 400)
    if not _is_supported_media_url(url):
        return _error_response("Invalid or unsupported URL. Use YouTube or Instagram links.", 400)

    job_prefix = _build_job_prefix("video")
    job_id = uuid.uuid4().hex
    _create_job(job_id, job_prefix)

    thread = threading.Thread(
        target=_download_worker,
        args=(job_id, "video", url, job_prefix),
        daemon=True,
    )
    thread.start()
    return jsonify({"job_id": job_id, "status": "downloading"}), 202


@app.post("/download/audio")
def download_audio():
    """Start an async audio download job and return a job_id for polling."""
    url = request.form.get("url", "").strip()
    if not url:
        return _error_response("Missing required form field: url", 400)
    if not _is_supported_media_url(url):
        return _error_response("Invalid or unsupported URL. Use YouTube or Instagram links.", 400)

    job_prefix = _build_job_prefix("audio")
    job_id = uuid.uuid4().hex
    _create_job(job_id, job_prefix)

    thread = threading.Thread(
        target=_download_worker,
        args=(job_id, "audio", url, job_prefix),
        daemon=True,
    )
    thread.start()
    return jsonify({"job_id": job_id, "status": "downloading"}), 202


@app.get("/progress")
def progress():
    """Return current progress for a job_id."""
    job_id = request.args.get("job_id", "").strip()
    if not job_id:
        return _error_response("Missing required query param: job_id", 400)

    job = _get_job(job_id)
    if not job:
        return _error_response("Job not found", 404)

    return jsonify(
        {
            "percentage": int(job.get("percentage", 0)),
            "status": job.get("status", "error"),
            "message": job.get("message", ""),
        }
    )


@app.get("/download/file/<job_id>")
def download_file(job_id: str):
    """Return the completed file for a finished job."""
    job = _get_job(job_id)
    if not job:
        return _error_response("Job not found", 404)
    if job.get("status") != "finished":
        return _error_response("Download is not ready yet", 409)

    file_path = job.get("file_path", "")
    file_name = job.get("file_name", "")
    job_prefix = job.get("job_prefix", "")
    if not file_path or not os.path.exists(file_path):
        return _error_response("Downloaded file is unavailable", 410)

    @after_this_request
    def _cleanup_after_response(response):
        if job_prefix:
            _cleanup_job_files(job_prefix)
        _delete_job(job_id)
        return response

    mimetype = "audio/mpeg" if file_name.lower().endswith(".mp3") else "video/mp4"
    return send_file(
        file_path,
        as_attachment=True,
        download_name=file_name,
        mimetype=mimetype,
    )


# -----------------------------------------------------------------------------
# Local development entry point
# -----------------------------------------------------------------------------
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
