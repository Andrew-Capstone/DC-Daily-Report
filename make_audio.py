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
import os, re, sys, glob, json, datetime, subprocess, urllib.request

ROOT = os.path.dirname(os.path.abspath(__file__))
VOICE = os.environ.get("PIPER_VOICE", "en_US-ryan-high")
MODEL_DIR = os.path.expanduser(os.environ.get("PIPER_MODEL_DIR", "~/.piper-voices"))

# KEEP_DAYS controls audio pruning; tolerate a garbage env value rather than crash.
try:
    KEEP_DAYS = int(os.environ.get("AUDIO_KEEP_DAYS", "90"))
except ValueError:
    print("Warning: AUDIO_KEEP_DAYS is not an integer; falling back to 90.")
    KEEP_DAYS = 90

MIN_ONNX_BYTES = 5 * 1024 * 1024  # a real piper .onnx is tens of MB


def _download(url, target):
    """Download to <target>.part then atomically move into place on success."""
    part = target + ".part"
    try:
        urllib.request.urlretrieve(url, part)
        os.replace(part, target)
    except BaseException:
        # never leave a partial file behind to poison a later run
        if os.path.exists(part):
            os.remove(part)
        raise


def _remove_model(onnx):
    for p in (onnx, onnx + ".json"):
        if os.path.exists(p):
            os.remove(p)


def _valid_model(onnx):
    """.onnx must be > 5 MB and .onnx.json must parse as JSON."""
    try:
        if not (os.path.exists(onnx) and os.path.exists(onnx + ".json")):
            return False
        if os.path.getsize(onnx) <= MIN_ONNX_BYTES:
            return False
        with open(onnx + ".json", encoding="utf-8") as f:
            json.load(f)
        return True
    except (OSError, ValueError):
        return False


def ensure_model():
    os.makedirs(MODEL_DIR, exist_ok=True)
    onnx = os.path.join(MODEL_DIR, VOICE + ".onnx")

    # Piper voice IDs are <lang>-<name>-<quality>, e.g. "en_US-ryan-high".
    # Voice *names* use underscores (never hyphens), so quality and name are
    # always the last two hyphen-separated segments. rsplit("-", 2) therefore
    # keeps any extra structure inside the lang tag intact and still gives us
    # exactly three parts for a well-formed ID. A 2-part ID like "badvoice-high"
    # yields only two parts and is rejected below.
    parts = VOICE.rsplit("-", 2)
    if len(parts) != 3:
        sys.exit(
            f"PIPER_VOICE '{VOICE}' is not in <lang>-<name>-<quality> form "
            f"(e.g. en_US-ryan-high). Set PIPER_VOICE correctly and retry."
        )
    lang, name, quality = parts
    base = (f"https://huggingface.co/rhasspy/piper-voices/resolve/v1.0.0/"
            f"{lang.split('_')[0]}/{lang}/{name}/{quality}/{VOICE}")

    def fetch():
        print(f"Downloading voice model {VOICE} ...")
        _download(base + ".onnx", onnx)
        _download(base + ".onnx.json", onnx + ".json")

    # A cached copy is only trusted if it passes the sanity check.
    if _valid_model(onnx):
        return onnx

    # Missing or corrupt: (re)download, and if still bad re-download once more.
    for _ in range(2):
        _remove_model(onnx)
        try:
            fetch()
        except Exception as e:  # network / HTTP error
            print(f"Download error: {e}")
        if _valid_model(onnx):
            return onnx

    _remove_model(onnx)
    sys.exit(
        f"Voice model {VOICE} is still invalid after re-download "
        f"(.onnx must be > 5 MB and .onnx.json must be valid JSON)."
    )


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

    def run_piper(m):
        return subprocess.run([sys.executable, "-m", "piper", "-m", m, "-f", wav],
                              input=text, capture_output=True, text=True)

    r = run_piper(model)
    if r.returncode != 0 or not os.path.exists(wav):
        # A silently corrupt cached model can make piper fail even though the
        # size/JSON checks passed — nuke it and rebuild once before giving up.
        print("Piper failed; discarding cached model and retrying once ...")
        _remove_model(os.path.join(MODEL_DIR, VOICE + ".onnx"))
        model = ensure_model()
        r = run_piper(model)
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
