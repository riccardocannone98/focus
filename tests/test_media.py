import random
import wave

import pytest

from focus_guard.media import IMAGE_EXTENSIONS, MusicPlayer, RandomPicker, list_files


def touch(folder, *names):
    for n in names:
        (folder / n).write_bytes(b"")


def test_list_files_filters_extensions(tmp_path):
    touch(tmp_path, "a.PNG", "b.jpg", "c.txt", "d.webp")
    (tmp_path / "sub.png").mkdir()
    assert [p.name for p in list_files(tmp_path, IMAGE_EXTENSIONS)] == ["a.PNG", "b.jpg", "d.webp"]


def test_missing_or_empty_folder(tmp_path):
    assert RandomPicker(tmp_path / "nope", IMAGE_EXTENSIONS).pick() is None
    assert RandomPicker(tmp_path, IMAGE_EXTENSIONS).pick() is None


def test_picker_never_repeats_consecutively(tmp_path):
    touch(tmp_path, "a.png", "b.png", "c.png")
    picker = RandomPicker(tmp_path, IMAGE_EXTENSIONS, random.Random(0))
    picks = [picker.pick() for _ in range(50)]
    assert all(a != b for a, b in zip(picks, picks[1:]))
    assert {p.name for p in picks} == {"a.png", "b.png", "c.png"}


def test_picker_single_file_repeats(tmp_path):
    touch(tmp_path, "only.png")
    picker = RandomPicker(tmp_path, IMAGE_EXTENSIONS)
    assert picker.pick() == picker.pick() == tmp_path / "only.png"


def test_music_without_files_is_noop(tmp_path):
    player = MusicPlayer(tmp_path)
    assert player.play() is None
    player.stop()  # non deve esplodere


def _write_wav(path, seconds=1.0, rate=22050):
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(b"\x00\x00" * int(seconds * rate))


def test_music_loop_and_immediate_stop(tmp_path, monkeypatch):
    pytest.importorskip("pygame")
    monkeypatch.setenv("SDL_AUDIODRIVER", "dummy")
    _write_wav(tmp_path / "track.wav")
    player = MusicPlayer(tmp_path, volume=0.3)
    try:
        assert player.play() == tmp_path / "track.wav"
        assert player.playing
        player.stop()
        assert not player.playing
    finally:
        player.close()
