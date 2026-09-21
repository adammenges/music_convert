#!/usr/bin/env python3
"""A safe, local FLAC-to-MP3 library manager."""

from __future__ import annotations

import json
import os
import queue
import shutil
import subprocess
import tempfile
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable

import tkinter as tk
from tkinter import filedialog, messagebox, ttk


BITRATE = 320_000
BITRATE_TOLERANCE = 1_000


@dataclass(frozen=True)
class AudioPair:
    """FLAC/MP3 files that share the same relative path and filename stem."""

    key: str
    flac: Path | None = None
    mp3: Path | None = None
    mp3_bitrate: int | None = None
    mp3_verified: bool = False
    probe_error: str | None = None

    @property
    def status(self) -> str:
        if self.flac and self.mp3:
            return "Converted · safe to delete FLAC" if self.mp3_verified else "Needs 320 kbps conversion"
        if self.flac:
            return "FLAC only"
        return "MP3 only"

    @property
    def formats(self) -> str:
        values = []
        if self.flac:
            values.append("FLAC")
        if self.mp3:
            values.append("MP3")
        return " + ".join(values)

    @property
    def mp3_location(self) -> str:
        return str(self.mp3) if self.mp3 else "—"

    @property
    def bitrate_label(self) -> str:
        return f"{round(self.mp3_bitrate / 1000)} kbps" if self.mp3_bitrate else "—"


def executable_available(name: str) -> bool:
    return shutil.which(name) is not None


def probe_mp3(path: Path) -> tuple[bool, int | None, str | None]:
    """Return whether *path* is a valid MP3 at approximately 320 kbps."""

    try:
        result = subprocess.run(
            [
                "ffprobe", "-v", "error", "-select_streams", "a:0",
                "-show_entries", "stream=codec_name,bit_rate:format=bit_rate",
                "-of", "json", str(path),
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        data = json.loads(result.stdout)
        streams = data.get("streams") or []
        if not streams:
            return False, None, "No audio stream"
        stream = streams[0]
        codec = stream.get("codec_name")
        raw_rate = stream.get("bit_rate") or (data.get("format") or {}).get("bit_rate")
        bitrate = int(raw_rate) if raw_rate else None
        verified = codec == "mp3" and bitrate is not None and bitrate >= BITRATE - BITRATE_TOLERANCE
        error = None if verified else "MP3 is missing or below 320 kbps"
        return verified, bitrate, error
    except (OSError, subprocess.SubprocessError, ValueError, json.JSONDecodeError) as exc:
        return False, None, str(exc)


def scan_library(root: Path) -> list[AudioPair]:
    """Scan recursively and pair FLAC/MP3 files by relative path and stem."""

    found: dict[str, dict[str, Path]] = {}
    for path in root.rglob("*"):
        if not path.is_file() or path.suffix.lower() not in {".flac", ".mp3"}:
            continue
        relative = path.relative_to(root)
        key = str(relative.with_suffix("")).casefold()
        found.setdefault(key, {})[path.suffix.lower()] = path

    pairs: list[AudioPair] = []
    for paths in sorted(found.values(), key=lambda value: str(next(iter(value.values()))).casefold()):
        flac = paths.get(".flac")
        mp3 = paths.get(".mp3")
        verified, bitrate, error = probe_mp3(mp3) if mp3 else (False, None, None)
        display_key = str((flac or mp3).relative_to(root).with_suffix(""))
        pairs.append(AudioPair(display_key, flac, mp3, bitrate, verified, error))
    return pairs


def convert_flac(source: Path, destination: Path) -> None:
    """Convert to a temporary file, verify it, then atomically install it."""

    destination.parent.mkdir(parents=True, exist_ok=True)
    file_descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{destination.stem}-", suffix=".mp3", dir=destination.parent
    )
    os.close(file_descriptor)
    temporary = Path(temporary_name)
    try:
        subprocess.run(
            [
                "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
                "-i", str(source), "-map", "0:a:0", "-map", "0:v?",
                "-map_metadata", "0", "-c:a", "libmp3lame", "-b:a", "320k",
                "-id3v2_version", "3", "-c:v", "copy", str(temporary),
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        verified, _, error = probe_mp3(temporary)
        if not verified:
            raise RuntimeError(f"Converted file failed verification: {error}")
        temporary.replace(destination)
    finally:
        temporary.unlink(missing_ok=True)


def safe_flac_candidates(pairs: Iterable[AudioPair]) -> list[AudioPair]:
    return [pair for pair in pairs if pair.flac and pair.mp3 and pair.mp3_verified]


class MusicConvertApp:
    FILTERS = (
        "All music",
        "Converted · safe to delete FLAC",
        "FLAC only",
        "MP3 only",
        "Needs 320 kbps conversion",
    )

    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("Music Convert")
        self.root.geometry("1180x720")
        self.root.minsize(900, 540)
        self.folder: Path | None = None
        self.pairs: list[AudioPair] = []
        self.events: queue.Queue[tuple[str, object]] = queue.Queue()
        self.busy = False

        self.folder_var = tk.StringVar(value="Choose a music folder to begin")
        self.filter_var = tk.StringVar(value=self.FILTERS[0])
        self.summary_var = tk.StringVar(value="No library scanned")
        self.progress_var = tk.StringVar(value="Ready")
        self._configure_style()
        self._build()
        self.root.after(100, self._drain_events)

    def _configure_style(self) -> None:
        style = ttk.Style()
        if "aqua" in style.theme_names():
            style.theme_use("aqua")
        style.configure("Title.TLabel", font=("TkDefaultFont", 22, "bold"))
        style.configure("Summary.TLabel", font=("TkDefaultFont", 12))
        style.configure("Danger.TButton", foreground="#b42318")
        style.configure("Treeview", rowheight=27)

    def _build(self) -> None:
        container = ttk.Frame(self.root, padding=20)
        container.pack(fill="both", expand=True)

        ttk.Label(container, text="Music Convert", style="Title.TLabel").pack(anchor="w")
        ttk.Label(container, text="Find, convert, and safely clean up FLAC and MP3 files.").pack(
            anchor="w", pady=(2, 16)
        )

        toolbar = ttk.Frame(container)
        toolbar.pack(fill="x", pady=(0, 12))
        self.choose_button = ttk.Button(toolbar, text="Choose folder…", command=self.choose_folder)
        self.choose_button.pack(side="left")
        self.rescan_button = ttk.Button(toolbar, text="Rescan", command=self.scan, state="disabled")
        self.rescan_button.pack(side="left", padx=(8, 0))
        ttk.Label(toolbar, textvariable=self.folder_var).pack(side="left", padx=14)

        info = ttk.Frame(container)
        info.pack(fill="x", pady=(0, 10))
        ttk.Label(info, textvariable=self.summary_var, style="Summary.TLabel").pack(side="left")
        filter_box = ttk.Combobox(
            info, values=self.FILTERS, textvariable=self.filter_var, state="readonly", width=31
        )
        filter_box.pack(side="right")
        filter_box.bind("<<ComboboxSelected>>", lambda _event: self.render())
        ttk.Label(info, text="Show:").pack(side="right", padx=(0, 6))

        table_frame = ttk.Frame(container)
        table_frame.pack(fill="both", expand=True)
        columns = ("status", "formats", "bitrate", "mp3")
        self.tree = ttk.Treeview(table_frame, columns=columns, show="tree headings", selectmode="extended")
        self.tree.heading("#0", text="Track / relative path")
        self.tree.heading("status", text="Status")
        self.tree.heading("formats", text="Formats")
        self.tree.heading("bitrate", text="MP3 quality")
        self.tree.heading("mp3", text="MP3 location")
        self.tree.column("#0", width=270, minwidth=160)
        self.tree.column("status", width=235, minwidth=180)
        self.tree.column("formats", width=95, minwidth=80)
        self.tree.column("bitrate", width=100, minwidth=90)
        self.tree.column("mp3", width=420, minwidth=220)
        scrollbar = ttk.Scrollbar(table_frame, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=scrollbar.set)
        self.tree.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        footer = ttk.Frame(container)
        footer.pack(fill="x", pady=(12, 0))
        ttk.Label(footer, textvariable=self.progress_var).pack(side="left")
        self.delete_button = ttk.Button(
            footer, text="Delete verified FLAC…", style="Danger.TButton",
            command=self.delete_selected, state="disabled",
        )
        self.delete_button.pack(side="right")
        self.convert_button = ttk.Button(
            footer, text="Convert to 320 kbps MP3", command=self.convert_selected, state="disabled"
        )
        self.convert_button.pack(side="right", padx=(0, 8))

    def choose_folder(self) -> None:
        selected = filedialog.askdirectory(title="Choose your music folder", mustexist=True)
        if selected:
            self.folder = Path(selected).resolve()
            self.folder_var.set(str(self.folder))
            self.scan()

    def _start_job(self, message: str, job: Callable[[], object]) -> None:
        if self.busy:
            return
        self.busy = True
        self.progress_var.set(message)
        self._set_controls()

        def runner() -> None:
            try:
                self.events.put(("done", job()))
            except Exception as exc:
                self.events.put(("error", exc))

        threading.Thread(target=runner, daemon=True).start()

    def scan(self) -> None:
        if self.folder:
            folder = self.folder
            self._start_job("Scanning and verifying MP3 quality…", lambda: ("scan", scan_library(folder)))

    def _selected_pairs(self) -> list[AudioPair]:
        keys = set(self.tree.selection())
        return [pair for pair in self.pairs if pair.key in keys]

    def convert_selected(self) -> None:
        selected = self._selected_pairs()
        source_pairs = selected if selected else self.pairs
        candidates = [pair for pair in source_pairs if pair.flac and not pair.mp3_verified]
        if not candidates:
            messagebox.showinfo(
                "Nothing to convert",
                "The selected tracks already have verified 320 kbps MP3s."
                if selected
                else "All FLAC files already have verified 320 kbps MP3s.",
            )
            return

        overwrite_count = sum(pair.mp3 is not None for pair in candidates)
        detail = f"Convert {len(candidates)} FLAC file(s) to 320 kbps MP3?"
        if overwrite_count:
            detail += f"\n\n{overwrite_count} existing lower-quality or invalid MP3 file(s) will be replaced."
        if not messagebox.askokcancel("Confirm conversion", detail):
            return

        def job() -> tuple[str, int, list[tuple[str, str]]]:
            failures: list[tuple[str, str]] = []
            completed = 0
            for index, pair in enumerate(candidates, start=1):
                self.events.put(("progress", f"Converting {index}/{len(candidates)}: {pair.key}"))
                try:
                    convert_flac(pair.flac, pair.flac.with_suffix(".mp3"))
                    completed += 1
                except Exception as exc:
                    failures.append((pair.key, str(exc)))
            return "convert", completed, failures

        self._start_job(f"Preparing to convert {len(candidates)} file(s)…", job)

    def delete_selected(self) -> None:
        selected = self._selected_pairs()
        candidates = safe_flac_candidates(selected or self.pairs)
        if not candidates:
            messagebox.showinfo(
                "Nothing safe to delete", "Select converted tracks, or rescan to verify their 320 kbps MP3 files."
            )
            return
        names = "\n".join(f"• {pair.key}.flac" for pair in candidates[:8])
        if len(candidates) > 8:
            names += f"\n• …and {len(candidates) - 8} more"
        if not messagebox.askyesno(
            "Permanently delete FLAC files?",
            f"This cannot be undone. Every MP3 will be verified again first.\n\n{names}",
            icon="warning",
        ):
            return

        def job() -> tuple[str, int, list[tuple[str, str]]]:
            failures: list[tuple[str, str]] = []
            deleted = 0
            for pair in candidates:
                verified, _, error = probe_mp3(pair.mp3)
                if not verified:
                    failures.append((pair.key, f"MP3 re-verification failed: {error}"))
                    continue
                try:
                    pair.flac.unlink()
                    deleted += 1
                except OSError as exc:
                    failures.append((pair.key, str(exc)))
            return "delete", deleted, failures

        self._start_job(f"Re-verifying and deleting {len(candidates)} FLAC file(s)…", job)

    def _drain_events(self) -> None:
        try:
            while True:
                event, payload = self.events.get_nowait()
                if event == "progress":
                    self.progress_var.set(str(payload))
                elif event == "error":
                    self.busy = False
                    self.progress_var.set("Operation failed")
                    messagebox.showerror("Music Convert", str(payload))
                    self._set_controls()
                elif event == "done":
                    self.busy = False
                    result = payload
                    if result[0] == "scan":
                        self.pairs = result[1]
                        self.render()
                        self.progress_var.set(f"Scan complete · {len(self.pairs)} track(s)")
                    else:
                        action, count, failures = result
                        verb = "Converted" if action == "convert" else "Deleted"
                        self.progress_var.set(f"{verb} {count} file(s)")
                        if failures:
                            details = "\n".join(f"{name}: {error}" for name, error in failures[:10])
                            messagebox.showwarning(f"{verb} with errors", details)
                        self.scan()
                    self._set_controls()
        except queue.Empty:
            pass
        self.root.after(100, self._drain_events)

    def _set_controls(self) -> None:
        normal = "disabled" if self.busy else "normal"
        self.choose_button.configure(state=normal)
        self.rescan_button.configure(state=normal if self.folder else "disabled")
        self.convert_button.configure(state=normal if self.pairs else "disabled")
        can_delete = bool(safe_flac_candidates(self.pairs))
        self.delete_button.configure(state=normal if can_delete else "disabled")

    def render(self) -> None:
        self.tree.delete(*self.tree.get_children())
        selected_filter = self.filter_var.get()
        visible = self.pairs if selected_filter == "All music" else [
            pair for pair in self.pairs if pair.status == selected_filter
        ]
        for pair in visible:
            self.tree.insert(
                "", "end", iid=pair.key, text=pair.key,
                values=(pair.status, pair.formats, pair.bitrate_label, pair.mp3_location),
            )

        converted = sum(pair.mp3_verified and pair.flac is not None for pair in self.pairs)
        flac_only = sum(pair.flac is not None and pair.mp3 is None for pair in self.pairs)
        mp3_only = sum(pair.mp3 is not None and pair.flac is None for pair in self.pairs)
        needs = sum(pair.flac is not None and pair.mp3 is not None and not pair.mp3_verified for pair in self.pairs)
        self.summary_var.set(
            f"{len(self.pairs)} tracks  ·  {converted} converted  ·  {flac_only} FLAC only  ·  "
            f"{mp3_only} MP3 only  ·  {needs} need conversion"
        )
        self._set_controls()


def main() -> int:
    missing = [name for name in ("ffmpeg", "ffprobe") if not executable_available(name)]
    if missing:
        root = tk.Tk()
        root.withdraw()
        messagebox.showerror(
            "FFmpeg is required",
            f"Missing: {', '.join(missing)}\n\nRun ./scripts/bootstrap.sh, then start Music Convert again.",
        )
        return 1
    root = tk.Tk()
    MusicConvertApp(root)
    root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
