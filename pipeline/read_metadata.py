"""Read a video's on-screen song metadata for human confirmation.

Samples a few frames and asks Gemini ONCE for the text that is literally
visible: title, artist, capo, tuning, time signature. Prints the answer
as JSON and as ready-to-paste save_song.py flags. Per the project's M1
rule: AI may read TEXT, a human confirms every value before it is saved
— this script never writes anything itself.

Example:
  .venv/bin/python pipeline/read_metadata.py <video.MP4>
"""
import argparse
import json
import os
import sys
from pathlib import Path

import cv2

sys.path.insert(0, str(Path(__file__).resolve().parent))
from m1_spike import call_gemini  # noqa: E402


def read(video, frames=3):
    """One batched Gemini call over sampled frames -> metadata dict.
    Values are whatever text is literally on screen; human confirms."""
    from google import genai
    from google.genai import types
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).resolve().parent.parent / ".env")
    client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])

    cap = cv2.VideoCapture(video)
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    parts = []
    for f in range(frames):
        cap.set(cv2.CAP_PROP_POS_FRAMES, int(total * (f + 0.5) / frames))
        ok, frame = cap.read()
        if not ok:
            continue
        ok, jpg = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 88])
        parts.append(types.Part.from_bytes(data=jpg.tobytes(), mime_type="image/jpeg"))
    cap.release()
    if not parts:
        raise RuntimeError("could not read any frames")

    parts.append(
        "These are frames from one guitar tutorial video. Report ONLY text that is "
        "literally visible on screen — do not guess from your own knowledge. "
        'Respond with ONLY this JSON, using null for anything not shown: '
        '{"title": ..., "artist": ..., "capo": <int|null>, "tuning": ..., '
        '"time_signature": ...}')
    resp = call_gemini(client, parts)
    text = (resp.text or "").strip().strip("`")
    text = text[4:] if text.startswith("json") else text
    return json.loads(text)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("video")
    ap.add_argument("--frames", type=int, default=3, help="frames to sample")
    args = ap.parse_args()
    meta = read(args.video, args.frames)

    print(json.dumps(meta, indent=2))
    print("\nVERIFY against the video, then save with e.g.:")
    flags = []
    if meta.get("title"):
        flags.append(f'--title "{meta["title"]}"')
    if meta.get("artist"):
        flags.append(f'--artist "{meta["artist"]}"')
    if meta.get("capo"):
        flags.append(f'--capo {meta["capo"]}')
    if meta.get("tuning") and str(meta["tuning"]).upper() not in ("STANDARD", "STANDARD TUNING"):
        flags.append(f'--tuning "{meta["tuning"]}"')
    if meta.get("time_signature"):
        flags.append(f'--time-sig "{meta["time_signature"]}"')
    print(f"  save_song.py <extraction.json> {' '.join(flags) or '--title ...'}")


if __name__ == "__main__":
    main()
