from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, HttpUrl
import os, time, httpx, datetime

app = FastAPI(
    title="YTLarge-GPT",
    version="1.0.0",
    description="YouTube metadata API without GPT dependency"
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
