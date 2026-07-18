"""Audio preprocessing for browser-recorded speech chunks."""

from __future__ import annotations

import base64
import binascii
import io
import math
import re

from pydub import AudioSegment

from app.config import settings


SUPPORTED_AUDIO_FORMATS = frozenset({"wav", "wave", "webm", "ogg", "opus", "mp3", "mpeg", "mp4", "m4a"})
_GROUPED_NUMBER_RE = re.compile(r"(?<![\d.,])\d{1,3}(?:[.,]\d{3})+(?![\d.,])")


def normalize_transcribed_text(text: str) -> str:
    """Normalize STT spacing and unambiguous thousand separators.

    Decimal GPS values and space-separated phone numbers are deliberately left
    unchanged. Price extraction later applies stricter context checks.
    """

    normalized = " ".join(text.split())
    return _GROUPED_NUMBER_RE.sub(lambda match: re.sub(r"[.,]", "", match.group(0)), normalized)


def _strip_data_url(audio_base64: str) -> str:
    value = audio_base64.strip()
    if value.startswith("data:") and "," in value:
        return value.split(",", 1)[1]
    return value


def _normalized_format(input_format: str) -> str:
    fmt = (input_format or "webm").lower().split(";", 1)[0].strip()
    if "/" in fmt:
        fmt = fmt.rsplit("/", 1)[1]
    if fmt == "x-m4a":
        fmt = "m4a"
    if fmt not in SUPPORTED_AUDIO_FORMATS:
        supported = ", ".join(sorted(SUPPORTED_AUDIO_FORMATS))
        raise ValueError(f"unsupported audio_format; supported formats: {supported}")
    return "wav" if fmt == "wave" else fmt


def preprocess_audio_for_stt(
    audio_base64: str,
    input_format: str = "webm",
    *,
    max_bytes: int | None = None,
    max_duration_seconds: int | None = None,
) -> bytes:
    """Convert Base64 browser audio to WAV PCM 16-bit, 16kHz, mono.

    Supports raw Base64 and `data:audio/...;base64,...` strings. WebM/MP3/MP4
    decoding requires ffmpeg in the runtime image.
    """
    payload = _strip_data_url(audio_base64)
    byte_limit = max_bytes if max_bytes is not None else settings.max_audio_bytes
    duration_limit = (
        max_duration_seconds
        if max_duration_seconds is not None
        else settings.max_audio_duration_seconds
    )
    encoded_limit = 4 * math.ceil(byte_limit / 3) + 4
    if len(payload) > encoded_limit:
        raise ValueError(f"audio exceeds the {byte_limit}-byte limit")

    fmt = _normalized_format(input_format)
    try:
        raw_bytes = base64.b64decode(payload, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise ValueError("audio_base64 is not valid Base64") from exc

    if not raw_bytes:
        raise ValueError("audio_base64 is empty")
    if len(raw_bytes) > byte_limit:
        raise ValueError(f"audio exceeds the {byte_limit}-byte limit")

    audio_stream = io.BytesIO(raw_bytes)
    try:
        segment = AudioSegment.from_file(audio_stream, format=fmt)
    except Exception:
        audio_stream.seek(0)
        try:
            segment = AudioSegment.from_file(audio_stream)
        except Exception as exc:
            raise ValueError(f"could not decode audio as {fmt}") from exc

    if segment.duration_seconds > duration_limit:
        raise ValueError(f"audio duration exceeds the {duration_limit}-second limit")

    segment = segment.set_channels(1).set_frame_rate(16000).set_sample_width(2)

    if math.isfinite(segment.max_dBFS):
        segment = segment.apply_gain(-3.0 - segment.max_dBFS)

    out_buf = io.BytesIO()
    segment.export(out_buf, format="wav")
    return out_buf.getvalue()
