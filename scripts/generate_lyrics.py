import os
import subprocess
import requests
from mutagen import File
from mutagen.easyid3 import EasyID3
from mutagen.id3 import ID3, USLT, SYLT,  TXXX,  Encoding
from difflib import SequenceMatcher
import json
import re
from mutagen.mp4 import MP4, MP4Tags
from mutagen.flac import FLAC

def normalize(text):
    text = text.lower()
    text = re.sub(r"[^\w\s']", "", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text

MEDIA_DIR = "/media/songs"
UNSYNCED_WORK_DIR = "/media/work/unsynced"
SYNCED_WORK_DIR = "/media/work/synced"

os.makedirs(UNSYNCED_WORK_DIR, exist_ok=True)
os.makedirs(SYNCED_WORK_DIR, exist_ok=True)

###########################################################
# 1. INTERNET LYRICS FETCH
#
# Attempts to fetch lyrics from the internet (lrclib.net)
# if artist and title metadata are available. Used as the
# first step to obtain plain and synced lyrics before
# falling back to WhisperX.
###########################################################
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


###########################################################
# 2. WHISPER FALLBACK
#
# If no lyrics are found from the internet, uses WhisperX
# to generate unsynced lyrics (plain text) from the audio.
###########################################################
def generate_txt_whisper(mp3_path, txt_path):
    print("[WHISPER] generating unsynced lyrics")

    base_filename =  os.path.splitext(os.path.basename(mp3_path))[0]
    generated = os.path.join(UNSYNCED_WORK_DIR, base_filename + ".txt")
    if not os.path.exists(generated):
        cmd = [
            "whisperx",
            mp3_path,
            "--model", "large-v3",
            "--output_format", "txt",
            "--output_dir", UNSYNCED_WORK_DIR
        ]
        whisperx_lang = os.environ.get("WHISPERX_LANGUAGE")
        if whisperx_lang:
            cmd += ["--language", whisperx_lang]
        subprocess.run(cmd, check=True)
    else:
        print(f"[WHISPER] Unsynced lyrics already generated: {generated}")
    if os.path.exists(generated):
        # Read the generated lyrics and split for better readability
        with open(generated, "r", encoding="utf-8") as f:
            text = f.read()

        import re
        import math
        # Split by punctuation (.,!?) or capital letter (not at start)
        split_regex = r'(?<=[.!?])\s+|(?<!^)\s+(?=[A-ZÉÈÀÂÎÔÛÇ])'
        raw_lines = re.split(split_regex, text)
        split_lines = []
        for line in raw_lines:
            words = line.strip().split()
            n = len(words)
            if n == 0:
                continue
            # Split into ceil(n/10) chunks, each as close as possible in size
            if n <= 12:
                split_lines.append(' '.join(words))
            else:
                num_chunks = math.ceil(n / 10)
                chunk_size = math.ceil(n / num_chunks)
                for i in range(0, n, chunk_size):
                    chunk = words[i:i+chunk_size]
                    split_lines.append(' '.join(chunk))
        # Remove any accidental empty lines
        split_lines = [l for l in split_lines if l.strip()]
        # Write to the real txt_path in MEDIA_DIR
        with open(txt_path, "w", encoding="utf-8") as f:
            for l in split_lines:
                f.write(l + "\n")
        print(f"[WHISPER] Unsynced lyrics written to {txt_path} (balanced split by punctuation/capital, no single-word lines)")

###########################################################
# 3. LRC GENERATION
#
# Generates a restructured WhisperX JSON file that aligns
# word-level timestamps to the structure of the .txt lyrics.
# Also provides LRC file generation from the restructured JSON.
###########################################################
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
        whisperx_lang = os.environ.get("WHISPERX_LANGUAGE")
        if whisperx_lang:
            cmd += ["--language", whisperx_lang]
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

###########################################################
# 4. ASS GENERATION
#
# Generates a karaoke-style ASS subtitle file using the
# restructured JSON segments for word-level timing.
###########################################################
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

def add_lyrics_tags(mp3_path, txt_path, lrc_path):
    """
    Add unsynced (plain) and synced (LRC) lyrics as tags to the audio file if not already present.
    Supports MP3 (ID3), M4A/MP4 (MP4 tags), and FLAC (Vorbis comments).
    """
    ext = os.path.splitext(mp3_path)[1].lower()
    # MP3: ID3 tags
    if ext == ".mp3":
        try:
            audio = ID3(mp3_path)
        except Exception:
            print(f"[TAGS] Could not open MP3 file for tagging: {mp3_path}")
            return
        # Unsynced lyrics (USLT)
        if os.path.exists(txt_path):
            try:
                with open(txt_path, "r", encoding="utf-8") as f:
                    txt_lyrics = f.read().strip()
                has_uslt = any(frame.FrameID == 'USLT' for frame in audio.values())
                if not has_uslt and txt_lyrics:
                    audio.add(USLT(encoding=Encoding.UTF8, lang='eng', desc='', text=txt_lyrics))
                    print(f"[TAGS] Added unsynced lyrics (USLT) to {mp3_path}")
            except Exception as e:
                print(f"[TAGS] Error adding unsynced lyrics: {e}")
        # Synced lyrics (SYLT)
        if os.path.exists(lrc_path):
            try:
                with open(lrc_path, "r", encoding="utf-8") as f:
                    lrc_lyrics = f.read().strip()
                has_sylt = any(frame.FrameID == 'SYLT' for frame in audio.values())
                if not has_sylt and lrc_lyrics:
                    audio.add(SYLT(encoding=Encoding.UTF8, lang='eng', format=2, type=1, desc='', text=lrc_lyrics, sync=[]))
                    # Add fallback Navidrome-friendly tag
                    audio.add(TXXX(
                        encoding=Encoding.UTF8,
                        desc="LYRICS",
                        text=txt_lyrics
                    ))
                    print(f"[TAGS] Added synced lyrics (SYLT) to {mp3_path}")
            except Exception as e:
                print(f"[TAGS] Error adding synced lyrics: {e}")
        try:
            audio.save(v2_version=3)
        except Exception as e:
            print(f"[TAGS] Error saving tags: {e}")
        return

    # M4A/MP4: MP4 tags
    if ext in {".m4a", ".mp4", ".m4b", ".m4p"}:
        try:
            audio = MP4(mp3_path)
        except Exception:
            print(f"[TAGS] Could not open MP4/M4A file for tagging: {mp3_path}")
            return
        changed = False
        # Unsynced lyrics
        if os.path.exists(txt_path):
            try:
                with open(txt_path, "r", encoding="utf-8") as f:
                    txt_lyrics = f.read().strip()
                if txt_lyrics and not audio.tags.get('\xa9lyr'):
                    audio.tags['\xa9lyr'] = [txt_lyrics]
                    audio.tags['----:com.apple.iTunes:LYRICS'] = [txt_lyrics.encode("utf-8")]
                    audio.tags['----:com.apple.iTunes:UNSYNCEDLYRICS'] = [txt_lyrics.encode("utf-8")]
                    print(f"[TAGS] Added unsynced lyrics (\xa9lyr) to {mp3_path}")
                    changed = True
            except Exception as e:
                print(f"[TAGS] Error adding unsynced lyrics: {e}")
        # Synced lyrics (custom atom)
        if os.path.exists(lrc_path):
            try:
                with open(lrc_path, "r", encoding="utf-8") as f:
                    lrc_lyrics = f.read().strip()
                if lrc_lyrics and not audio.tags.get('----:com.apple.iTunes:SYLT'):
                    audio.tags['----:com.apple.iTunes:SYLT'] = [lrc_lyrics.encode('utf-8')]
                    print(f"[TAGS] Added synced lyrics (SYLT atom) to {mp3_path}")
                    changed = True
            except Exception as e:
                print(f"[TAGS] Error adding synced lyrics: {e}")
        if changed:
            try:
                audio.save(v2_version=3)
            except Exception as e:
                print(f"[TAGS] Error saving tags: {e}")
        return

    # FLAC: Vorbis comments
    if ext == ".flac":
        try:
            audio = FLAC(mp3_path)
        except Exception:
            print(f"[TAGS] Could not open FLAC file for tagging: {mp3_path}")
            return
        changed = False
        # Unsynced lyrics
        if os.path.exists(txt_path):
            try:
                with open(txt_path, "r", encoding="utf-8") as f:
                    txt_lyrics = f.read().strip()
                if txt_lyrics and 'LYRICS' not in audio:
                    audio['LYRICS'] = txt_lyrics
                    print(f"[TAGS] Added unsynced lyrics (LYRICS) to {mp3_path}")
                    changed = True
            except Exception as e:
                print(f"[TAGS] Error adding unsynced lyrics: {e}")
        # Synced lyrics (custom tag)
        if os.path.exists(lrc_path):
            try:
                with open(lrc_path, "r", encoding="utf-8") as f:
                    lrc_lyrics = f.read().strip()
                if lrc_lyrics and 'SYLT' not in audio:
                    audio['SYLT'] = lrc_lyrics
                    print(f"[TAGS] Added synced lyrics (SYLT) to {mp3_path}")
                    changed = True
            except Exception as e:
                print(f"[TAGS] Error adding synced lyrics: {e}")
        if changed:
            try:
                audio.save(v2_version=3)
            except Exception as e:
                print(f"[TAGS] Error saving tags: {e}")
        return

    # Other formats: not supported
    print(f"[TAGS] Tagging not supported for this file type: {mp3_path}")
    """
    Add unsynced (plain) and synced (LRC) lyrics as tags to the audio file if not already present.
    Uses USLT (unsynced) and SYLT (synced) ID3 frames.
    """
    try:
        audio = ID3(mp3_path)
    except Exception:
        print(f"[TAGS] Could not open file for tagging: {mp3_path}")
        return

    # Add unsynced lyrics (from txt) as USLT
    if os.path.exists(txt_path):
        try:
            with open(txt_path, "r", encoding="utf-8") as f:
                txt_lyrics = f.read().strip()
            has_uslt = any(frame.FrameID == 'USLT' for frame in audio.values())
            if not has_uslt and txt_lyrics:
                audio.add(USLT(encoding=Encoding.UTF8, lang='eng', desc='', text=txt_lyrics))
                print(f"[TAGS] Added unsynced lyrics (USLT) to {mp3_path}")
        except Exception as e:
            print(f"[TAGS] Error adding unsynced lyrics: {e}")

    # Add synced lyrics (from lrc) as SYLT (best effort, stores as text)
    if os.path.exists(lrc_path):
        try:
            with open(lrc_path, "r", encoding="utf-8") as f:
                lrc_lyrics = f.read().strip()
            has_sylt = any(frame.FrameID == 'SYLT' for frame in audio.values())
            if not has_sylt and lrc_lyrics:
                # Note: Proper SYLT requires parsing LRC into time/text pairs. Here we store as text for compatibility.
                audio.add(SYLT(encoding=Encoding.UTF8, lang='eng', format=2, type=1, desc='', text=lrc_lyrics, sync=[]))
                print(f"[TAGS] Added synced lyrics (SYLT) to {mp3_path}")
        except Exception as e:
            print(f"[TAGS] Error adding synced lyrics: {e}")

    try:
        audio.save(v2_version=3)
    except Exception as e:
        print(f"[TAGS] Error saving tags: {e}")

###########################################################
# 5. MAIN PIPELINE
# Main pipeline for a single audio file. Checks file type,
# determines paths, and runs each enabled step (internet fetch,
# unsynced lyrics, synced LRC, karaoke ASS) as needed.
###########################################################
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
    generate_unsynced_env = os.environ.get("GENERATE_UNSYNCED_LYRICS", "false").lower() == "true"
    generate_synced_env = os.environ.get("GENERATE_SYNCED_LYRICS", "false").lower() == "true"
    generate_karaoke_env = os.environ.get("GENERATE_KARAOKE_LYRICS", "false").lower() == "true"
    fetch_from_web_env = os.environ.get("FETCH_FROM_WEB", "false").lower() == "true"
    add_lyrics_tags_env = os.environ.get("ADD_LYRICS_TAGS", "false").lower() == "true"

    # ------------------------- 
    # STEP 1: INTERNET LOOKUP (optional)
    # -------------------------
    if fetch_from_web_env and (not os.path.exists(txt_path) or not os.path.exists(lrc_path)):
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
    if generate_unsynced_env and not os.path.exists(txt_path):
        generate_txt_whisper(mp3_path, txt_path)

    # -------------------------
    # STEP 3: LRC GENERATION (synced)
    # -------------------------
    if generate_synced_env and os.path.exists(txt_path) and not os.path.exists(lrc_path):
        generate_lrc(mp3_path, txt_path, lrc_path)
    
    # -------------------------
    # STEP 4: ASS GENERATION (karaoke)
    # -------------------------
    if generate_karaoke_env and os.path.exists(txt_path) and not os.path.exists(ass_path):
        # Always generate the JSON file first, then use it for both ASS and
        generate_ass(mp3_path, txt_path, ass_path)  # This now just reads the JSON

    # -------------------------
    # STEP 5: ADD LYRICS TAGS (unsynced and synced)
    # -------------------------
    if add_lyrics_tags_env:
        add_lyrics_tags(mp3_path, txt_path, lrc_path)

def main():
    for root, _, files in os.walk(MEDIA_DIR):
        for f in files:
            if f.startswith("."):
                continue
            process(os.path.join(root, f))

if __name__ == "__main__":
    main()