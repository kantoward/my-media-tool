import os
import uuid
import shutil
import subprocess
from pathlib import Path

import cv2
from flask import Flask, request, render_template, send_file, after_this_request
from PIL import Image, ImageDraw, ImageFont

BASE = Path(__file__).resolve().parent
WORK = BASE / "work"
WORK.mkdir(exist_ok=True)

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 500 * 1024 * 1024  # 500 MB


def safe_font(size=48):
    candidates = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/System/Library/Fonts/Supplemental/Arial.ttf",
        "C:/Windows/Fonts/arial.ttf",
    ]
    for p in candidates:
        if os.path.exists(p):
            return ImageFont.truetype(p, size=size)
    return ImageFont.load_default()


def cleanup(path):
    try:
        if Path(path).is_dir():
            shutil.rmtree(path, ignore_errors=True)
        elif Path(path).exists():
            Path(path).unlink(missing_ok=True)
    except Exception:
        pass


def process_image(src, dst, mode, text, x, y, w, h):
    img = cv2.imread(str(src), cv2.IMREAD_UNCHANGED)
    if img is None:
        raise ValueError("无法读取图片")

    if mode == "remove":
        mask = __import__("numpy").zeros(img.shape[:2], dtype="uint8")
        x, y, w, h = [max(0, int(v)) for v in (x, y, w, h)]
        x2 = min(mask.shape[1], x + w)
        y2 = min(mask.shape[0], y + h)
        if x2 <= x or y2 <= y:
            raise ValueError("去水印区域无效")
        mask[y:y2, x:x2] = 255
        result = cv2.inpaint(img[:, :, :3] if img.ndim == 3 else img, mask, 5, cv2.INPAINT_TELEA)
        cv2.imwrite(str(dst), result)
        return

    # Add text watermark with Pillow for predictable font rendering.
    if img.ndim == 3 and img.shape[2] == 4:
        rgba = cv2.cvtColor(img, cv2.COLOR_BGRA2RGBA)
        pil = Image.fromarray(rgba)
    else:
        rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
        pil = Image.fromarray(rgb).convert("RGBA")

    draw = ImageDraw.Draw(pil, "RGBA")
    font = safe_font(max(16, min(160, int(pil.width * 0.055))))
    pad = max(10, int(pil.width * 0.02))
    bbox = draw.textbbox((0, 0), text, font=font, stroke_width=2)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    px = pad if x is None else int(max(0, min(pil.width - tw - pad, x)))
    py = pad if y is None else int(max(0, min(pil.height - th - pad, y)))

    # Semi-transparent black backing makes white text readable.
    draw.rounded_rectangle(
        [px - 12, py - 8, px + tw + 12, py + th + 8],
        radius=12, fill=(0, 0, 0, 90)
    )
    draw.text((px, py), text, font=font, fill=(255, 255, 255, 235),
              stroke_width=2, stroke_fill=(0, 0, 0, 160))
    out = pil.convert("RGB")
    out.save(dst, quality=95)


def run_ffmpeg(args):
    p = subprocess.run(
        ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y"] + args,
        capture_output=True, text=True
    )
    if p.returncode != 0:
        raise RuntimeError(p.stderr[-2000:] or "FFmpeg 处理失败")


def process_video(src, dst, mode, text, x, y, w, h):
    # Probe dimensions first.
    probe = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0",
         "-show_entries", "stream=width,height", "-of", "csv=p=0", str(src)],
        capture_output=True, text=True
    )
    if probe.returncode != 0:
        raise RuntimeError("无法读取视频信息")
    vals = probe.stdout.strip().split(",")
    if len(vals) != 2:
        raise RuntimeError("无法读取视频尺寸")
    vw, vh = map(int, vals)

    if mode == "remove":
        # Fixed rectangular inpainting via OpenCV. Audio is copied when possible.
        cap = cv2.VideoCapture(str(src))
        fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
        fourcc = cv2.VideoWriter_fourcc(*"mp4v")
        temp_video = dst.with_name("video_only.mp4")
        writer = cv2.VideoWriter(str(temp_video), fourcc, fps, (vw, vh))
        if not writer.isOpened():
            cap.release()
            raise RuntimeError("无法创建视频输出文件")

        import numpy as np
        xx, yy, ww, hh = [int(v) for v in (x, y, w, h)]
        xx = max(0, min(vw - 1, xx))
        yy = max(0, min(vh - 1, yy))
        ww = max(1, min(vw - xx, ww))
        hh = max(1, min(vh - yy, hh))
        mask = np.zeros((vh, vw), dtype=np.uint8)
        mask[yy:yy+hh, xx:xx+ww] = 255

        while True:
            ok, frame = cap.read()
            if not ok:
                break
            fixed = cv2.inpaint(frame, mask, 5, cv2.INPAINT_TELEA)
            writer.write(fixed)
        cap.release()
        writer.release()

        # Reattach original audio if present.
        run_ffmpeg([
            "-i", str(temp_video), "-i", str(src),
            "-map", "0:v:0", "-map", "1:a?",
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "22",
            "-c:a", "aac", "-b:a", "128k", "-movflags", "+faststart",
            str(dst)
        ])
        temp_video.unlink(missing_ok=True)
        return

    # Text watermark: FFmpeg drawtext. Escape special characters.
    import re
    t = text or "My Watermark"
    t = re.sub(r"([\\':])", r"\\\1", t)
    px = 20 if x is None else max(0, int(x))
    py = 20 if y is None else max(0, int(y))
    vf = (
        f"drawtext=fontfile=/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf:"
        f"text='{t}':x={px}:y={py}:fontsize=42:"
        f"fontcolor=white@0.92:borderw=2:bordercolor=black@0.75"
    )
    run_ffmpeg([
        "-i", str(src), "-vf", vf,
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "22",
        "-c:a", "aac", "-b:a", "128k", "-movflags", "+faststart",
        str(dst)
    ])


@app.get("/")
def index():
    return render_template("index.html")


@app.post("/process")
def process():
    if "file" not in request.files:
        return {"error": "请选择图片或视频"}, 400

    f = request.files["file"]
    if not f.filename:
        return {"error": "文件名为空"}, 400

    mode = request.form.get("mode", "add")
    text = request.form.get("text", "").strip()
    try:
        x = int(float(request.form.get("x", "20")))
        y = int(float(request.form.get("y", "20")))
        w = int(float(request.form.get("w", "100")))
        h = int(float(request.form.get("h", "100")))
    except ValueError:
        return {"error": "坐标参数无效"}, 400

    job = WORK / uuid.uuid4().hex
    job.mkdir()
    src = job / Path(f.filename).name
    f.save(src)

    ext = src.suffix.lower()
    image_exts = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}
    video_exts = {".mp4", ".mov", ".m4v", ".webm", ".avi", ".mkv"}

    try:
        if ext in image_exts:
            out = job / "result.jpg"
            process_image(src, out, mode, text, x, y, w, h)
            mimetype = "image/jpeg"
            download_name = "result.jpg"
        elif ext in video_exts:
            out = job / "result.mp4"
            process_video(src, out, mode, text, x, y, w, h)
            mimetype = "video/mp4"
            download_name = "result.mp4"
        else:
            cleanup(job)
            return {"error": "目前支持 JPG/PNG/WEBP/BMP 和 MP4/MOV/M4V/WEBM/AVI/MKV"}, 400

        @after_this_request
        def remove_job(response):
            cleanup(job)
            return response

        return send_file(out, mimetype=mimetype, as_attachment=True,
                         download_name=download_name, max_age=0)
    except Exception as e:
        cleanup(job)
        return {"error": str(e)}, 500


@app.errorhandler(413)
def too_large(_):
    return {"error": "文件超过 500 MB 上限"}, 413


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "8080")))
