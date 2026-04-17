# Karaoke Lyrics Generation Pipeline

This project provides a pipeline for generating synchronized lyrics (LRC/ASS) for audio files using WhisperX and internet lyric sources. The workflow is controlled by environment variables and processes audio and lyric files in a robust, reproducible way.

## Directory Structure

- `media/songs/` — Place your audio files (any format supported by WhisperX, e.g. `.m4a`, `.mp3`, `.wav`, `.flac`, `.ogg`, `.aac`, `.wma`, `.mp4`, `.mkv`, `.opus`, `.webm`, `.mov`, `.avi`, `.m4b`) and optional `.txt` lyric files here.
- `media/work/` — Intermediate and output files are written here.
- `media/work/synced/` — Synchronized JSON and LRC/ASS files.
- `scripts/generate_lyrics.py` — Main pipeline script.

## Main Features

- **Internet Lyrics Fetch:** Attempts to fetch lyrics from lrclib.net if enabled.
- **WhisperX Fallback:** Uses WhisperX to generate unsynced lyrics if no `.txt` is found.
- **Synchronized JSON:** Generates a JSON file with word-level timestamps using WhisperX.
- **Segment Restructuring:** Aligns JSON segments to match the structure of the `.txt` file, ensuring no single-word segments.
- **LRC/ASS Generation:** Produces LRC and ASS files from the restructured JSON.
- **Environment Variable Control:** Pipeline steps are enabled/disabled via environment variables.

## Environment Variables

Set these variables in .env to control which steps run:

- `FETCH_FROM_WEB=true` — Try to fetch lyrics from the internet.
- `GENERATE_UNSYNCED_LYRICS=true` — Generate unsynced lyrics with WhisperX if `.txt` is missing.
- `GENERATE_SYNCED_LYRICS=true` — Generate LRC file from JSON.
- `GENERATE_KARAOKE_LYRICS=true` — Generate ASS karaoke file from JSON.
- `ADD_LYRICS_TAGS=true` — Add unsynced and synced lyrics as tags to audio files (if supported by format)

## How to Run

1. Place your audio files (any format supported by WhisperX, e.g. `.m4a`, `.mp3`, `.wav`, `.flac`, `.ogg`, `.aac`, `.wma`, `.mp4`, `.mkv`, `.opus`, `.webm`, `.mov`, `.avi`, `.m4b`) and optionally `.txt` lyric files in `media/songs/`.
2. Set the desired environment variables (see above).
3. Run the pipeline:

   ```sh
   docker compose up whisperx -d
   docker compose exec whisperx python3 -m ensurepip --upgrade
   docker compose exec whisperx python3 -m pip install --upgrade pip
   docker compose exec whisperx python3 -m pip install -r requirements.txt 
   docker compose exec whisperx python3 generate_lyrics.py
   ```
   or use the provided PowerShell script:
   ```sh
   ./run.ps1
   ```

4. Outputs will be written to `media/work/synced/`.

## Output Files

- `.json` — WhisperX word-level alignment output.
- `.txtstruct.json` — Segments restructured to match `.txt` lines.
- `.lrc` — Synchronized LRC file.
- `.ass` — Karaoke ASS file.

## Supported Audio Formats

The pipeline will process any of the following formats (as supported by WhisperX):

```
.m4a, .mp3, .wav, .flac, .ogg, .aac, .wma, .mp4, .mkv, .opus, .webm, .mov, .avi, .m4b
```

## Notes

- The pipeline checks for existing files and skips steps if outputs are already present.
- The segmenting logic ensures every recognized word is used and avoids single-word segments.
- For best results, provide clean `.txt` lyric files matching the audio.

## Troubleshooting

- Check the console output for detailed logs and error messages.
- Ensure all dependencies (WhisperX, Python packages) are installed.
- If you encounter issues, try deleting intermediate files in `media/work/` and rerunning.

---

For further customization or advanced usage, see the comments in `scripts/generate_lyrics.py`.
