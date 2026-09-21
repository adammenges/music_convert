from pathlib import Path
import tempfile
import unittest
from unittest import mock

import music_convert


class MusicConvertTests(unittest.TestCase):
    def test_scan_pairs_case_insensitive_extensions(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            album = root / "Album"
            album.mkdir()
            (album / "Song.FLAC").touch()
            (album / "Song.mp3").touch()
            (album / "notes.txt").touch()

            with mock.patch("music_convert.probe_mp3", return_value=(True, 320_000, None)):
                pairs = music_convert.scan_library(root)

            self.assertEqual(len(pairs), 1)
            self.assertEqual(pairs[0].key, "Album/Song")
            self.assertEqual(pairs[0].status, "Converted · safe to delete FLAC")

    def test_safe_candidates_require_both_files_and_verified_mp3(self) -> None:
        flac = Path("song.flac")
        mp3 = Path("song.mp3")
        pairs = [
            music_convert.AudioPair("safe", flac, mp3, 320_000, True),
            music_convert.AudioPair("low", flac, mp3, 128_000, False),
            music_convert.AudioPair("flac", flac, None),
            music_convert.AudioPair("mp3", None, mp3, 320_000, True),
        ]

        self.assertEqual(music_convert.safe_flac_candidates(pairs), [pairs[0]])

    def test_convert_uses_temporary_file_and_atomically_replaces(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "song.flac"
            destination = root / "song.mp3"
            source.write_bytes(b"flac")
            destination.write_bytes(b"old")

            def fake_run(command, **_kwargs):
                Path(command[-1]).write_bytes(b"new mp3")
                return mock.Mock(stdout="")

            with (
                mock.patch("music_convert.subprocess.run", side_effect=fake_run) as run,
                mock.patch("music_convert.probe_mp3", return_value=(True, 320_000, None)),
            ):
                music_convert.convert_flac(source, destination)

            self.assertEqual(destination.read_bytes(), b"new mp3")
            self.assertIn("320k", run.call_args.args[0])
            self.assertFalse(list(root.glob(".song-*.mp3")))
