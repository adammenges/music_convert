# Music Convert

A clean local desktop app for reviewing a music folder, converting FLAC audio to high-quality 320 kbps MP3, and removing FLAC originals only after the MP3 has been verified.

Nothing is uploaded. The app works directly with files on your Mac.

## What it does

- Scans a folder and all of its subfolders for `.flac` and `.mp3` files.
- Pairs files that have the same folder and filename, such as `Album/Song.flac` and `Album/Song.mp3`.
- Shows whether each track is FLAC-only, MP3-only, safely converted, or still needs a 320 kbps conversion.
- Converts FLAC audio to constant 320 kbps MP3 with FFmpeg while preserving metadata and embedded artwork when possible.
- Writes conversions to a temporary file, verifies the result, and only then moves it into place. An existing lower-quality MP3 is not replaced unless conversion succeeds.
- Permanently deletes FLAC originals only when a matching MP3 passes a fresh 320 kbps verification immediately before deletion.

## Setup on macOS

Install [Homebrew](https://brew.sh) if it is not already installed, then run:

```bash
./scripts/bootstrap.sh
```

The setup script uses the included `Brewfile` to install FFmpeg, creates `.venv`, upgrades pip, and installs the Python requirements. The app itself uses only Python's standard library; `requirements.txt` is intentionally kept as the conventional home for future packages.

## Run

```bash
.venv/bin/python music_convert.py
```

Then:

1. Click **Choose folder…** and select the top-level folder containing your music.
2. Use the **Show** menu to filter by converted, FLAC-only, MP3-only, or needs-conversion status.
3. Select one or more rows and click **Convert to 320 kbps MP3**. If nothing is selected, the app offers to convert every FLAC that does not yet have a verified 320 kbps MP3.
4. Select converted rows and click **Delete verified FLAC…**. If nothing is selected, it offers all safe candidates. Read the confirmation carefully: deletion is permanent.

Converted MP3s are placed beside their FLAC sources with the same filename. For example:

```text
Music/Artist/Album/Track.flac
Music/Artist/Album/Track.mp3
```

## Safety notes

- “Converted” means `ffprobe` found an MP3 audio stream at approximately 320 kbps; a matching filename alone is not enough.
- Deletion re-checks each MP3 after confirmation. Any file that fails verification is skipped and reported.
- FLAC deletion uses permanent filesystem deletion, not the Trash.
- Conversion is lossy. Keep a backup if you may want lossless audio later.
- If an existing MP3 is below 320 kbps or invalid, converting that row replaces it only after a new output passes verification.

## Tests

```bash
.venv/bin/python -m unittest discover -s tests
```
