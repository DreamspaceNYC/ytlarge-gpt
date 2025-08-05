from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel, HttpUrl
import subprocess
import os
import uuid
import time
import shutil
import datetime

app = FastAPI(
    title="YTLarge-GPT",
    version="1.2.0",
    description="YouTube metadata API using yt-dlp — supports transcript, mp3, download, and analysis"
)

class AnalyzeRequest(BaseModel):
    url: HttpUrl

@app.get("/", tags=["Service"])
def read_root():
    return {"name": "YTLarge-GPT", "version": "1.2.0", "status": "running"}

@app.get("/health", tags=["Health"])
def health_check():
    return {"status": "healthy", "timestamp": datetime.datetime.utcnow().isoformat() + "Z"}

@app.post("/analyze", tags=["Analysis"])
def analyze(req: AnalyzeRequest):
    start = time.time()
    video_id = str(req.url).split("v=")[-1].split("&")[0]
    api_key = os.getenv("YOUTUBE_API_KEY")
    if not api_key:
        raise HTTPException(status_code=500, detail="Missing YouTube API key.")
    import httpx
    url = (
        f"https://www.googleapis.com/youtube/v3/videos"
        f"?part=snippet,statistics,contentDetails&id={video_id}&key={api_key}"
    )
    r = httpx.get(url)
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
    return {
        "analysis": "Metadata retrieved successfully",
        "metadata": meta,
        "processing_time": round(time.time() - start, 2)
    }

@app.get("/transcript", tags=["Transcript"])
def get_transcript(video_url: str = Query(..., description="Full YouTube video URL")):
    video_id = video_url.split("v=")[-1].split("&")[0]
    temp_id = str(uuid.uuid4())
    subtitle_file = f"{temp_id}.en.vtt"
    try:
        subprocess.run([
            "yt-dlp",
            "--skip-download",
            "--write-auto-sub",
            "--sub-lang", "en",
            "-o", temp_id,
            video_url
        ], check=True)
        if not os.path.exists(subtitle_file):
            raise HTTPException(404, detail="Transcript not available.")
        with open(subtitle_file, "r", encoding="utf-8") as f:
            lines = [line.strip() for line in f if "-->" not in line and line.strip() and not line[0].isdigit()]
        return {"transcript": lines}
    except subprocess.CalledProcessError:
        raise HTTPException(500, detail="Failed to retrieve transcript using yt-dlp.")
    finally:
        if os.path.exists(subtitle_file):
            os.remove(subtitle_file)

@app.get("/mp3", tags=["Audio"])
def convert_to_mp3(video_url: str):
    filename = f"{uuid.uuid4()}.mp3"
    try:
        subprocess.run([
            "yt-dlp",
            "-x", "--audio-format", "mp3",
            "-o", filename,
            video_url
        ], check=True)
        if not os.path.exists(filename):
            raise HTTPException(500, detail="MP3 conversion failed.")
        return {"filename": filename}
    finally:
        if os.path.exists(filename):
            os.remove(filename)

@app.get("/download", tags=["Download"])
def download(video_url: str, audio_only: bool = False):
    ext = "mp3" if audio_only else "mp4"
    filename = f"{uuid.uuid4()}.{ext}"
    cmd = [
        "yt-dlp",
        "-o", filename,
    ]
    if audio_only:
        cmd += ["-x", "--audio-format", "mp3"]
    cmd.append(video_url)
    try:
        subprocess.run(cmd, check=True)
        if not os.path.exists(filename):
            raise HTTPException(500, detail="Download failed.")
        return {"filename": filename}
    finally:
        if os.path.exists(filename):
            os.remove(filename)
