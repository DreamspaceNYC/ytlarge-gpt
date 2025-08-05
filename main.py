from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, HttpUrl
from typing import List
import os, time, httpx, datetime, uuid, subprocess

from youtube_transcript_api import YouTubeTranscriptApi, TranscriptsDisabled, NoTranscriptFound
import yt_dlp

app = FastAPI(
    title="YTLarge-GPT",
    version="1.0.0",
    description="YouTube metadata API without GPT dependency"
)

YOUTUBE_API_KEY = os.getenv("YOUTUBE_API_KEY")
if not YOUTUBE_API_KEY:
    raise RuntimeError("Missing env YOUTUBE_API_KEY")

# ========== MODELS ==========

class AnalyzeRequest(BaseModel):
    url: HttpUrl

class AnalyzeResponse(BaseModel):
    analysis: str
    metadata: dict
    processing_time: float

class DownloadRequest(BaseModel):
    url: HttpUrl
    format: str  # 'mp4' or 'mp3'

class Segment(BaseModel):
    start: float
    end: float

class ClipRequest(BaseModel):
    url: HttpUrl
    segments: List[Segment]

# ========== EXISTING ROUTES ==========

@app.get("/", tags=["Service"])
def read_root():
    return {"name": "YTLarge-GPT", "version": "1.0.0", "status": "running"}

@app.get("/health", tags=["Health"])
def health_check():
    return {"status": "healthy", "timestamp": datetime.datetime.utcnow().isoformat() + "Z"}

@app.post("/analyze", tags=["Analysis"])
async def analyze(req: AnalyzeRequest):
    start = time.time()
    video_id = str(req.url).split("v=")[-1].split("&")[0]
    url = (
        "https://www.googleapis.com/youtube/v3/videos"
        f"?part=snippet,statistics,contentDetails"
        f"&id={video_id}&key={YOUTUBE_API_KEY}"
    )
    async with httpx.AsyncClient() as client:
        r = await client.get(url)
        if r.status_code != 200:
            raise HTTPException(400, "Invalid YouTube URL or quota exceeded")
        data = r.json()
        if not data["items"]:
            raise HTTPException(400, "Video not found")
        item = data["items"][0]
    meta = {
        "title": item["snippet"]["title"],
        "description": item["snippet"].get("description", ""),
        "duration": item["contentDetails"]["duration"],
        "view_count": int(item["statistics"].get("viewCount", 0)),
        "like_count": int(item["statistics"].get("likeCount", 0)),
        "channel_name": item["snippet"]["channelTitle"],
        "upload_date": item["snippet"]["publishedAt"][:10],
    }
    return AnalyzeResponse(
        analysis="YouTube metadata retrieved successfully",
        metadata=meta,
        processing_time=round(time.time() - start, 2)
    )

# ========== NEW ROUTES ==========

@app.post("/download", tags=["Utility"])
def download_video(req: DownloadRequest):
    if req.format not in ["mp4", "mp3"]:
        raise HTTPException(400, "Invalid format. Use 'mp4' or 'mp3'.")

    uid = str(uuid.uuid4())
    out_file = f"{uid}.%(ext)s"
    output_dir = "downloads"
    os.makedirs(output_dir, exist_ok=True)

    ydl_opts = {
        "outtmpl": f"{output_dir}/{out_file}",
        "format": "bestaudio/best" if req.format == "mp3" else "best",
        "postprocessors": [{
            "key": "FFmpegExtractAudio",
            "preferredcodec": "mp3",
            "preferredquality": "192",
        }] if req.format == "mp3" else [],
        "quiet": True,
    }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(str(req.url), download=True)
            final_file = ydl.prepare_filename(info)
            if req.format == "mp3":
                final_file = final_file.rsplit(".", 1)[0] + ".mp3"
    except Exception as e:
        raise HTTPException(500, f"Download failed: {str(e)}")

    return FileResponse(final_file, filename=os.path.basename(final_file))

@app.post("/transcript", tags=["Utility"])
def get_transcript(req: AnalyzeRequest):
    video_id = str(req.url).split("v=")[-1].split("&")[0]
    try:
        transcript = YouTubeTranscriptApi.get_transcript(video_id)
    except (TranscriptsDisabled, NoTranscriptFound):
        raise HTTPException(404, "Transcript not available for this video.")
    return {"transcript": transcript}

@app.post("/clip", tags=["Utility"])
def create_clip(req: ClipRequest):
    uid = str(uuid.uuid4())
    input_file = f"downloads/{uid}.mp4"
    os.makedirs("downloads", exist_ok=True)

    # Download full video
    ydl_opts = {
        "outtmpl": input_file,
        "format": "best",
        "quiet": True
    }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([str(req.url)])
    except Exception as e:
        raise HTTPException(500, f"Download failed: {str(e)}")

    # Create clips
    clip_paths = []
    for i, seg in enumerate(req.segments):
        clip_path = f"downloads/{uid}_part{i}.mp4"
        cmd = [
            "ffmpeg", "-y",
            "-i", input_file,
            "-ss", str(seg.start),
            "-to", str(seg.end),
            "-c", "copy", clip_path
        ]
        subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        clip_paths.append(f"file '{clip_path}'\n")

    # Create list file
    list_file = f"downloads/{uid}_list.txt"
    with open(list_file, "w") as f:
        f.writelines(clip_paths)

    # Concatenate
    final_output = f"downloads/{uid}_final.mp4"
    cmd_concat = [
        "ffmpeg", "-y",
        "-f", "concat",
        "-safe", "0",
        "-i", list_file,
        "-c", "copy",
        final_output
    ]
    subprocess.run(cmd_concat, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    return FileResponse(final_output, filename=os.path.basename(final_output))
