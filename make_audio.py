#!/usr/bin/env python3
"""
Generate the MP3 narration for a daily report.

Usage:   python3 make_audio.py <narration.txt> <YYYY-MM-DD>
Output:  audio/<YYYY-MM-DD>.mp3 (repo root), ~64kbps mono
Also prunes MP3s older than KEEP_DAYS (default 90).

Requires: piper-tts (pip install piper-tts), ffmpeg.
The voice model is loaded from PIPER_MODEL_DIR (default ~/.piper-voices)
and auto-downloaded from Hugging Face if missing.
Voice is set by PIPER_VOICE (default en_US-ryan-high — male, North American).
"""
import os, re, sys, glob, datetime, subprocess, urllib.request

ROOT = os.path.dirname(os.path.abspath(__file__))
VOICE = os.environ.get("PIPER_VOICE", "en_US-ryan-high")
MODEL_DIR = os.path.expanduser(os.environ.get("PIPER_MODEL_DIR", "~/.piper-voices"))
KEEP_DAYS = int(os.environ.get("AUDIO_KEEP_DAYS", "90"))

def ensure_model():
    os.makedirs(MODEL_DIR, exist_ok=True)
    onnx = os.path.join(MODEL_DIR, VOICE + ".onnx")
    if os.path.exists(onnx) and os.path.exists(onnx + ".json"):
        return onnx
    # en_US-ryan-high -> lang=en_US, name=ryan, quality=high
    lang, name, quality = VOICE.split("-")
    base = (f"https://huggingface.co/rhasspy/piper-voices/resolve/v1.0.0/"
            f"{lang.split('_')[0]}/{lang}/{name}/{quality}/{VOICE}")
    print(f"Downloading voice model {VOICE} ...")
    urllib.request.urlretrieve(base + ".onnx", onnx)
    urllib.request.urlretrieve(base + ".onnx.json", onnx + ".json")
    return onnx

def main():
    if len(sys.argv) != 3:
        sys.exit("Usage: make_audio.py <narration.txt> <YYYY-MM-DD>")
    text_file, date_iso = sys.argv[1], sys.argv[2]
    if not re.match(r"^\d{4}-\d{2}-\d{2}$", date_iso):
        sys.exit("Date must be YYYY-MM-DD")

    model = ensure_model()
    audio_dir = os.path.join(ROOT, "audio")
    os.makedirs(audio_dir, exist_ok=True)
    wav = f"/tmp/brief-{date_iso}.wav"
    mp3 = os.path.join(audio_dir, f"{date_iso}.mp3")

    with open(text_file, encoding="utf-8") as f:
        text = f.read().strip()

    r = subprocess.run([sys.executable, "-m", "piper", "-m", model, "-f", wav],
                       input=text, capture_output=True, text=True)
    if r.returncode != 0 or not os.path.exists(wav):
        sys.exit("Piper failed:\n" + r.stdout + r.stderr)

    r = subprocess.run(["ffmpeg", "-y", "-i", wav, "-ac", "1", "-b:a", "64k", mp3],
                       capture_output=True, text=True)
    if r.returncode != 0 or not os.path.exists(mp3):
        sys.exit("ffmpeg failed:\n" + r.stderr)
    os.remove(wav)

    # prune old audio
    cutoff = (datetime.date.fromisoformat(date_iso)
              - datetime.timedelta(days=KEEP_DAYS)).isoformat()
    for f in glob.glob(os.path.join(audio_dir, "*.mp3")):
        m = re.match(r"^(\d{4}-\d{2}-\d{2})\.mp3$", os.path.basename(f))
        if m and m.group(1) < cutoff:
            os.remove(f)
            print("Pruned", os.path.basename(f))

    size = os.path.getsize(mp3) // 1024
    print(f"Created audio/{date_iso}.mp3 ({size} KB)")

if __name__ == "__main__":
    main()
