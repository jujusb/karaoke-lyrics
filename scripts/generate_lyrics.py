import os
import subprocess
import requests
from mutagen import File
from mutagen.easyid3 import EasyID3
from difflib import SequenceMatcher
import json
import re

def normalize(text):
    text = text.lower()
    text = re.sub(r"[^\w\s']", "", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text

MEDIA_DIR = "/media/songs"
WORK_DIR = "/media/work"
UNSYNCED_WORK_DIR = "/media/work/unsynced"
SYNCED_WORK_DIR = "/media/work/synced"
KARAOKE_WORK_DIR = "/media/work/karaoke"

os.makedirs(WORK_DIR, exist_ok=True)
os.makedirs(UNSYNCED_WORK_DIR, exist_ok=True)
os.makedirs(SYNCED_WORK_DIR, exist_ok=True)
os.makedirs(KARAOKE_WORK_DIR, exist_ok=True)

# -------------------------
# 1. INTERNET LYRICS FETCH
# -------------------------
def fetch_lyrics_from_internet(artist, title):
    print(f"[NET] Searching lyrics: {artist} - {title}")
    if not artist or not title:
        return None
    try:
        url = f"https://lrclib.net/api/get?artist_name={artist}&track_name={title}"
        r = requests.get(url, timeout=5)

        if r.status_code == 200:
            data = r.json()

            # synced lyrics exist
            return data

    except Exception as e:
        print("[NET] error:", e)

    return None


# -------------------------
# 2. WHISPER FALLBACK
# -------------------------
def generate_txt_whisper(mp3_path, txt_path):
    print("[WHISPER] generating unsynced lyrics")

    cmd = [
        "whisperx",
        mp3_path,
        "--model", "large-v3",
        "--output_format", "txt",
        "--output_dir", UNSYNCED_WORK_DIR
    ]

    subprocess.run(cmd, check=True)

    base_filename = os.path.basename(mp3_path)
    generated = os.path.join(UNSYNCED_WORK_DIR, base_filename + ".txt")
    if os.path.exists(generated):
        os.rename(generated, txt_path)

# -------------------------
# 3. LRC GENERATION
# -------------------------
def generate_lrc(mp3_path, txt_path, lrc_path):
    """
    Generate an LRC file using the restructured whisperx JSON (txtstruct.json), matching the structure of the txt file.
    """
    base_filename = os.path.splitext(os.path.basename(mp3_path))[0]
    json_path = os.path.join(SYNCED_WORK_DIR, base_filename + ".json")
    json_restructure_path = json_path.replace('.json', '.txtstruct.json')
    if not os.path.exists(json_restructure_path):
        # Ensure the restructured JSON exists
        generate_whisper_json(mp3_path, txt_path, json_path, json_restructure_path)
    if not os.path.exists(json_restructure_path):
        print(f"[LRC] Restructured JSON not found: {json_restructure_path}")
        return
    def fmt_lrc(t):
        m = int(t // 60)
        s = t % 60
        return f"[{m:02}:{s:05.2f}]"
    with open(json_restructure_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    segments = data.get("segments", [])
    with open(lrc_path, "w", encoding="utf-8") as f:
        for seg in segments:
            start = seg["start"]
            text = seg["text"]
            f.write(f"{fmt_lrc(start)}{text}\n")
    print(f"[LRC] LRC file generated: {lrc_path}")
    exit(0)

def generate_whisper_json(mp3_path, txt_path, json_path, json_restructure_path):
    """
    Generate whisperx JSON output for a given audio file and initial prompt (if provided).
    """
    if not os.path.exists(json_path):
        print(f"[WHISPER] generating JSON: {json_path}")
        cmd = [
            "whisperx",
            mp3_path,
            "--model", "large-v3",
            "--output_format", "json",
            "--output_dir", os.path.dirname(json_path)
        ]
        if txt_path and os.path.exists(txt_path):
            cmd += ["--initial_prompt", open(txt_path, encoding="utf-8").read()]
        subprocess.run(cmd, check=True)
        print(f"[WHISPER] JSON generated: {json_path}")
    else:
        print(f"[WHISPER] JSON already exists: {json_path}")
    if not os.path.exists(json_restructure_path):
        # If a txt_path is provided and exists, reformat the JSON to follow the disposition from the txt file
        if txt_path and os.path.exists(txt_path):
            try:
                with open(json_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                # Flatten all words from all segments
                all_words = []
                for seg in data.get("segments", []):
                    for w in seg.get("words", []):
                        all_words.append({
                            "word": normalize(w["word"]),
                            "start": w["start"],
                            "end": w["end"]
                        })
                    
                # Read lines from txt file
                ref_words = []
                line_breaks = []  # keeps track of where each line ends
                count = 0
                with open(txt_path, "r", encoding="utf-8") as f:
                    txt_lines = [line.strip() for line in f if line.strip()]

                    for line in txt_lines:
                        words = normalize(line).split()
                        ref_words.extend(words)
                        count += len(words)
                        line_breaks.append(count)

                whisper_tokens = [w["word"] for w in all_words]

                matcher = SequenceMatcher(None, whisper_tokens, ref_words)

                aligned = []  # list of (ref_word, whisper_word or None)

                w_idx = 0
                r_idx = 0

                for tag, i1, i2, j1, j2 in matcher.get_opcodes():
                    if tag == "equal":
                        for k in range(i2 - i1):
                            aligned.append((ref_words[j1 + k], all_words[i1 + k]))
                    elif tag == "replace":
                        for k in range(j2 - j1):
                            aligned.append((ref_words[j1 + k], None))
                    elif tag == "insert":
                        for k in range(j2 - j1):
                            aligned.append((ref_words[j1 + k], None))
                    elif tag == "delete":
                        continue
                merged_segments = []
                cursor = 0

                for line_idx, end_idx in enumerate(line_breaks):
                    line_words = aligned[cursor:end_idx]

                    timestamps = [w for (_, w) in line_words if w is not None]

                    if timestamps:
                        segment = {
                            "text": txt_lines[line_idx],
                            "start": timestamps[0]["start"],
                            "end": timestamps[-1]["end"],
                            "words": timestamps
                        }
                        merged_segments.append(segment)

                    cursor = end_idx
                # Write merged segments to a new file
                if merged_segments:
                    data["segments"] = merged_segments
                    with open(json_restructure_path, "w", encoding="utf-8") as f_out:
                        json.dump(data, f_out, ensure_ascii=False, indent=2)
                    print(f"[WHISPER] JSON segments restructured to match txt lines and use all words, no single-word segments. Written to {json_restructure_path}")
                    # Stop script after first json_restructure_path is generated
                    #exit(0)
            except Exception as e:
                print(f"[WHISPER] Error restructuring JSON segments: {e}")

# -------------------------
# 4. ASS GENERATION
# -------------------------
def generate_ass(mp3_path, txt_path, ass_path):
    print("[ASS] generating word karaoke")
    base_filename = os.path.splitext(os.path.basename(mp3_path))[0]
    json_path = os.path.join(SYNCED_WORK_DIR, base_filename + ".json")
    json_restructure_path=json_path.replace('.json', '.txtstruct.json')
    # Always generate the JSON file first
    generate_whisper_json(mp3_path, txt_path, json_path, json_restructure_path)

    def fmt(t):
        h = int(t // 3600)
        m = int((t % 3600) // 60)
        s = t % 60
        return f"{h}:{m:02}:{s:05.2f}"

    with open(json_restructure_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    with open(ass_path, "w", encoding="utf-8") as f:
        f.write("[Script Info]\nScriptType: v4.00+\n\n")
        f.write("[V4+ Styles]\n")
        f.write("Style: Default,Arial,48,&H00FFFFFF,&H0000FFFF,&H00000000,&H64000000,0,0,1,2,0,2,10,10,40,1\n\n")
        f.write("[Events]\nFormat: Layer, Start, End, Style, Text\n")

        for seg in data["segments"]:
            words = seg.get("words", [])
            if not words:
                continue

            start = words[0]["start"]
            end = words[-1]["end"]

            line = ""
            for w in words:
                dur = max(1, int((w["end"] - w["start"]) * 100))
                line += f"{{\\k{dur}}}{w['word'].strip()} "

            f.write(f"Dialogue: 0,{fmt(start)},{fmt(end)},Default,{line.strip()}\n")
    exit

######################
# Get Clean metadata
######################
def clean(text):
    return text.strip().replace("feat.", "").replace("(Official Video)", "")

def get_metadata(mp3_path):
    try:
        try:
            audio = EasyID3(mp3_path)
            artist = audio.get("artist", [""])[0]
            title = audio.get("title", [""])[0]
            print(f"[META EasyID3] {artist} - {title}")
        except Exception:
            audio = File(mp3_path, easy=True)
            if not audio:
                return "", ""
            artist = audio.get("artist", [""])[0]
            title = audio.get("title", [""])[0]
            print(f"[META File] {artist} - {title}")
        return clean(artist), clean(title)
    except Exception:
        print("[META] error reading metadata")
        return "", ""

# -------------------------
# 5. MAIN PIPELINE
# -------------------------
def process(file):
    # Accept all common audio formats supported by whisperx
    SUPPORTED_EXTS = {'.m4a', '.mp3', '.wav', '.flac', '.ogg', '.aac', '.wma', '.mp4', '.mkv', '.opus', '.webm', '.mov', '.avi', '.m4b'}
    ext = os.path.splitext(file)[1].lower()
    if ext not in SUPPORTED_EXTS:
        return

    base = os.path.splitext(file)[0]
    mp3_path = os.path.join(MEDIA_DIR, file)
    txt_path = os.path.join(MEDIA_DIR, base + ".txt")
    lrc_path = os.path.join(MEDIA_DIR, base + ".lrc")
    ass_path = os.path.join(MEDIA_DIR, base + ".ass")

    # Check if the audio file exists
    if not os.path.exists(mp3_path):
        print(f"[NOT FOUND] {mp3_path} not found, skipping.")
        return

    artist, title = get_metadata(mp3_path)

    print(f"\n=== {base} ===")

    synced_from_net = False


    # Read environment variables for generation modes
    generate_unsynced = os.environ.get("GENERATE_UNSYNCED_LYRICS", "false").lower() == "true"
    generate_synced = os.environ.get("GENERATE_SYNCED_LYRICS", "false").lower() == "true"
    generate_karaoke = os.environ.get("GENERATE_KARAOKE_LYRICS", "false").lower() == "true"
    fetch_from_web = os.environ.get("FETCH_FROM_WEB", "false").lower() == "true"

    # ------------------------- 
    # STEP 1: INTERNET LOOKUP (optional)
    # -------------------------
    if fetch_from_web:
        lyrics = fetch_lyrics_from_internet(artist, title)

        if lyrics:
            print("[NET] lyrics found")
            if not os.path.exists(txt_path):
                if lyrics.get("plainLyrics"):
                    print("[NET] plain lyrics found")
                    with open(txt_path, "w", encoding="utf-8") as f:
                        f.write(lyrics["plainLyrics"])
                else:
                    print("[NET] plain lyrics NOT found in response")
            else:
                print(f"[NET] plain lyrics file already exists: {txt_path}")
            if not os.path.exists(lrc_path):
                if lyrics.get("syncedLyrics"):
                    print("[NET] synced lyrics found")
                    # directly write LRC
                    with open(lrc_path, "w", encoding="utf-8") as f:
                        f.write(lyrics["syncedLyrics"])
                    synced_from_net = True
                else:
                    print("[NET] synced lyrics NOT found in response")
            else:
                print(f"[NET] synced lyrics file already exists: {lrc_path}")
        else:
            print("[NET] lyrics NOT found from internet")

    # -------------------------
    # STEP 2: WHISPER FALLBACK (unsynced)
    # -------------------------
    if generate_unsynced and not os.path.exists(txt_path):
        generate_txt_whisper(mp3_path, txt_path)

    # -------------------------
    # STEP 3: LRC GENERATION (synced)
    # -------------------------
    if generate_synced and os.path.exists(txt_path) and not os.path.exists(lrc_path):
        generate_lrc(mp3_path, txt_path, lrc_path)

    # -------------------------
    # STEP 4: ASS GENERATION (karaoke)
    # -------------------------
    if generate_karaoke and os.path.exists(txt_path) and not os.path.exists(ass_path):
        # Always generate the JSON file first, then use it for both ASS and
        generate_ass(mp3_path, txt_path, ass_path)  # This now just reads the JSON

def main():
    for root, _, files in os.walk(MEDIA_DIR):
        for f in files:
            if not f.lower().endswith(".m4a"):
                continue
            if f.startswith("."):
                continue
            process(os.path.join(root, f))

if __name__ == "__main__":
    main()