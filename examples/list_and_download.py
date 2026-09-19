"""List the SD-card recordings of a Tapo "V4" camera and download the latest clip as MP4.
Needs ffmpeg on PATH and a .env with TAPO_HOST and TAPO_CLOUD_PASSWORD."""
import datetime as dt
import os
import subprocess
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from dotenv import dotenv_values  # noqa: E402

from tapo_v4.tapo_media import PLAYER_ID, ClipDemuxer, MediaSession, stream_clip  # noqa: E402
from tapo_v4.tapo_v4 import TapoV4  # noqa: E402

env = dotenv_values(".env")
host, pwd = env["TAPO_HOST"], env["TAPO_CLOUD_PASSWORD"]
cam = TapoV4(host, pwd)
print("camera:", cam.get_device_info()["device_model"], "| SD:", cam.get_sd_status()["status"])
days = sorted(cam.search_days("20200101", "20991231"))
print(len(days), "days with recordings, latest:", days[-1])
day = dt.datetime.strptime(days[-1], "%Y%m%d")
lo = int(day.timestamp())
clips = cam.search_videos_utc(lo, lo + 86399, PLAYER_ID)
for c in clips[-5:]:
    print("  ", dt.datetime.fromtimestamp(c["startTime"]), c["endTime"] - c["startTime"], "s")
start, end = clips[-1]["startTime"], clips[-1]["endTime"]
with open("clip.ts", "wb") as fv, open("clip.alaw", "wb") as fa, MediaSession(host, pwd) as sess:
    demux = ClipDemuxer(fv.write, fa.write)
    stream_clip(sess, start, end, demux)
    sess.stop()
subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-i", "clip.ts", "-itsoffset", f"{demux.audio_offset:.3f}",
                "-f", "alaw", "-ar", "8000", "-ac", "1", "-i", "clip.alaw", "-map", "0:v:0", "-map", "1:a:0?",
                "-c:v", "copy", "-c:a", "aac", "-movflags", "+faststart", "clip.mp4"], check=True)
print("wrote clip.mp4 (%.1f s of video)" % demux.video_seconds)
