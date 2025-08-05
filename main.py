from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel, HttpUrl
from typing import Optional
import os, time, httpx, datetime
from urllib.parse import urlparse, parse_qs
from youtube_transcript_api import YouTubeTranscriptApi, TranscriptsDisabled, NoTranscriptFound
import yt_dlp

app = FastAPI(
    title="YTLarge-GPT",
    version="1.0.0",
    description="YouTube metadata + transcript + downloader"
)

YOUTUBE_API_KEY = os.getenv("YOUTUBE_API_KEY")
if not YOUTUBE_API_KEY:
    raise RuntimeError("Missing env YOUTUBE_API_KEY")

class AnalyzeRequest(BaseModel):
    url: HttpUrl

class AnalyzeResponse(BaseModel):
    analysis: str
    metadata: dict
    processing_time: float

@app.get("/", tags=["Service"])
def read_root():
    return {"name": "YTLarge-GPT", "version": "1.0.0", "status": "running"}

@app.get("/health", tags=["Health"])
def health_check():
    return {"status": "healthy", "timestamp": datetime.datetime.utcnow().isoformat() + "Z"}

@app.post("/analyze", response_model=AnalyzeResponse, tags=["Analysis"])
async def analyze(req: AnalyzeRequest):
    start = time.time()
    parsed_url = urlparse(str(req.url))
    if "youtu.be" in parsed_url.netloc:
        video_id = parsed_url.path.lstrip("/")
    else:
        video_id = parse_qs(parsed_url.query).get("v", [None])[0]

    if not video_id:
        raise HTTPException(status_code=400, detail="Unable to extract video ID from URL")

    url = (
        "https://www.googleapis.com/youtube/v3/videos"
        f"?part=snippet,statistics,contentDetails"
        f"&id={video_id}&key={YOUTUBE_API_KEY}"
    )

    async with httpx.AsyncClient() as client:
        r = await client.get(url)
        if r.status_code != 200:
            raise HTTPException(status_code=400, detail="Invalid YouTube URL or quota exceeded")
        data = r.json()
        if not data.get("items"):
            raise HTTPException(status_code=404, detail="Video not found")

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

@app.get("/transcript", tags=["Transcript"])
def get_transcript(video_id: str):
    try:
        transcript = YouTubeTranscriptApi.get_transcript(video_id)
        return {"video_id": video_id, "transcript": transcript}
    except TranscriptsDisabled:
        raise HTTPException(status_code=404, detail="Transcript disabled")
    except NoTranscriptFound:
        raise HTTPException(status_code=404, detail="Transcript not found")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error: {str(e)}")

@app.get("/download", tags=["Download"])
def download_video(url: str, audio_only: bool = False):
    ydl_opts = {
        'format': 'bestaudio/best' if audio_only else 'best',
        'quiet': True,
        'noplaylist': True,
        'skip_download': True,
        'forceurl': True
    }
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=False)
        stream_url = info['url']
        return {
            "title": info.get("title"),
            "direct_url": stream_url,
            "is_audio": audio_only
        }

@app.get("/clip", tags=["Download"])
def download_clip(url: str, start: str = Query(...), end: str = Query(...)):
    """
    Returns the downloadable clip segment URL with timestamps.
    NOTE: Real clip rendering would require ffmpeg and storage support.
    """
    return {
        "message": "This is a simulated clip endpoint. Use ffmpeg backend for real clip cutting.",
        "url": url,
        "start": start,
        "end": end
    }

@app.get("/mp3", tags=["Download"])
def extract_mp3(url: str):
    ydl_opts = {
        'format': 'bestaudio/best',
        'quiet': True,
        'noplaylist': True,
        'skip_download': True,
        'forceurl': True,
        'postprocessors': [{
            'key': 'FFmpegExtractAudio',
            'preferredcodec': 'mp3',
            'preferredquality': '192',
        }],
    }
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=False)
        return {
            "title": info.get("title"),
            "mp3_url": info["url"],
            "duration": info.get("duration"),
        }
