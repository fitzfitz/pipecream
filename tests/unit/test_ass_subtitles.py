import sys

import pytest

from workers.step2_audio_subs import (
    build_dry_run_segments,
    format_ass_time,
    generate_ass_subtitles,
)
from workers.step4_render import escape_filter_path


def _words(*items):
    return [{"word": w, "start": s, "end": e} for w, s, e in items]


def _dialogues(path):
    return [l for l in path.read_text(encoding="utf-8").splitlines() if l.startswith("Dialogue:")]


def test_module_import_does_not_load_whisper():
    assert "mlx_whisper" not in sys.modules
    assert "kokoro_onnx" not in sys.modules


@pytest.mark.parametrize("seconds, expected", [
    (0, "0:00:00.00"),
    (1.5, "0:00:01.50"),
    (9.07, "0:00:09.07"),
    (61.25, "0:01:01.25"),
    (3661.07, "1:01:01.07"),
    (1.999, "0:00:02.00"),     # rounds up into the next second, never ".100"
    (59.996, "0:01:00.00"),    # carries into minutes
    (-0.5, "0:00:00.00"),      # clamps negatives
])
def test_format_ass_time(seconds, expected):
    assert format_ass_time(seconds) == expected


def test_header_resolution_and_sections(tmp_path):
    out = tmp_path / "subs.ass"
    generate_ass_subtitles([], out)
    text = out.read_text(encoding="utf-8")
    assert "PlayResX: 768" in text
    assert "PlayResY: 1344" in text
    for section in ("[Script Info]", "[V4+ Styles]", "[Events]"):
        assert section in text
    assert "Style: Default," in text
    assert _dialogues(out) == []


def test_three_word_uppercase_chunking(tmp_path):
    segments = [
        {"words": _words(("the", 0.0, 0.3), (" door", 0.3, 0.6), ("was", 0.6, 0.9))},
        {"words": _words(("locked", 1.0, 1.4), ("from", 1.4, 1.6), ("inside", 1.6, 2.0), ("again", 2.1, 2.5))},
    ]
    out = tmp_path / "subs.ass"
    generate_ass_subtitles(segments, out)
    lines = _dialogues(out)

    assert lines == [
        "Dialogue: 0,0:00:00.00,0:00:00.90,Default,,0,0,0,,THE DOOR WAS",
        "Dialogue: 0,0:00:01.00,0:00:02.00,Default,,0,0,0,,LOCKED FROM INSIDE",
        "Dialogue: 0,0:00:02.10,0:00:02.50,Default,,0,0,0,,AGAIN",
    ]


def test_chunking_skips_blank_words_and_strips_override_braces(tmp_path):
    segments = [{"words": _words(("{\\b1}hi", 0, 0.2), ("  ", 0.2, 0.3), ("there", 0.3, 0.5))}]
    out = tmp_path / "subs.ass"
    generate_ass_subtitles(segments, out)
    assert _dialogues(out) == ["Dialogue: 0,0:00:00.00,0:00:00.50,Default,,0,0,0,,\\B1HI THERE"]


def test_segments_without_words_key(tmp_path):
    out = tmp_path / "subs.ass"
    generate_ass_subtitles([{"text": "no word timings"}], out)
    assert _dialogues(out) == []


def test_dry_run_segments_produce_three_lines_over_three_seconds(tmp_path):
    out = tmp_path / "subs.ass"
    generate_ass_subtitles(build_dry_run_segments("Short narration"), out)
    lines = _dialogues(out)
    assert len(lines) == 3
    assert lines[0].startswith("Dialogue: 0,0:00:00.00,")
    assert lines[-1].split(",")[2] == "0:00:03.00"
    assert all(l.split(",,")[-1].isupper() for l in lines)


@pytest.mark.parametrize("path, expected", [
    ("/tmp/subs.ass", "/tmp/subs.ass"),
    ("/Users/me/My Videos/subs.ass", "/Users/me/My Videos/subs.ass"),
    ("/tmp/a:b/subs.ass", r"/tmp/a\\:b/subs.ass"),
    ("/tmp/it's/subs.ass", r"/tmp/it\\\'s/subs.ass"),
    ("/tmp/a,b[1];/subs.ass", r"/tmp/a\,b\[1\]\;/subs.ass"),
])
def test_ass_filter_path_escaping(path, expected):
    assert escape_filter_path(path) == expected
