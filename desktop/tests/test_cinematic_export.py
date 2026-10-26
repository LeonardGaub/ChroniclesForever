"""Video export: the cinematic replay rendered frame by frame into an MP4 file with its sound mixed in."""

import os
import subprocess

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from forever_chronicle.config import AppConfig  # noqa: E402
from forever_chronicle.ui.cinematic_export import (FPS, SAMPLES, TAIL, Cancelled, Recorder, export_video,  # noqa: E402
                                                   ffmpeg_exe)


def test_recorder_notes_effects_and_music(app):
    rec = Recorder(AppConfig())
    rec.music.start()
    assert rec.play("death") and not rec.play("death"), "the same effect not twice at once, as in the app"
    for _ in range(FPS):
        rec.step(1 / FPS)
    assert rec.effects == [(0.0, "death")] and len(rec.music_log) == FPS
    tracks, level = rec.music_log[-1]
    assert tracks and 0 < level < 1, "the music fades in"
    assert rec.play("death"), "a second later it may play again"


@pytest.mark.skipif(not ffmpeg_exe(), reason="ffmpeg (imageio-ffmpeg) not installed")
def test_export_writes_a_video_with_sound(ctx, imported, tmp_path):
    cid = ctx.repo.list_characters()[0].character_id
    start = ctx.repo.positions(cid)[0].time
    seen = []
    out = export_video(ctx, cid, start, start + 120, tmp_path / "replay.mp4", size=(320, 180), speed=10,
                       progress=lambda share: seen.append(share) or True)
    assert out.is_file() and out.stat().st_size > 1000
    assert seen and all(0 <= s <= 1 for s in seen)
    info = subprocess.run([ffmpeg_exe(), "-i", str(out)], capture_output=True).stderr.decode("utf-8", "replace")
    assert "Video: h264" in info and "320x180" in info, info
    assert "Audio: aac" in info, "music and sounds mixed in"
    assert not list(tmp_path.glob("replay.*.*")), "temporary files are removed"

    silent = export_video(ctx, cid, start, start + 60, tmp_path / "quiet.mp4", size=(320, 180), speed=10,
                          with_sound=False)
    info = subprocess.run([ffmpeg_exe(), "-i", str(silent)], capture_output=True).stderr.decode("utf-8", "replace")
    assert "Video: h264" in info and "Audio" not in info

    with pytest.raises(Cancelled):
        export_video(ctx, cid, start, start + 600, tmp_path / "stop.mp4", size=(320, 180), progress=lambda s: False)
    assert not (tmp_path / "stop.mp4").exists() and not list(tmp_path.glob("stop.*.*"))
    assert SAMPLES * FPS == 48000 and TAIL > 0
