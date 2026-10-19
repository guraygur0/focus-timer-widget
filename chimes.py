"""Synthesised phase chimes, written once as 16-bit WAV files (no downloads, stdlib only)."""
import math
import struct
import wave
from pathlib import Path

RATE = 44100
# (frequency Hz, start s, length s): soft bell notes with a few inharmonic partials.
CHIMES = {
    # focus finished -> short break: calm descending pair
    'short': [(1318.5, 0, 1.1), (1046.5, .22, 1.4)],
    # focus finished -> long break: slow, warm descending arpeggio
    'long': [(1568.0, 0, 1.2), (1318.5, .26, 1.2), (1046.5, .52, 1.4), (784.0, .78, 1.9)],
    # break finished -> focus: bright ascending triad
    'focus': [(523.3, 0, .9), (659.3, .14, .9), (784.0, .28, 1.3)],
}

def render(notes):
    total = max(start+length for _, start, length in notes)
    samples = [0.0]*(int(total*RATE)+2)
    for freq, start, length in notes:
        offset = int(start*RATE)
        for i in range(int(length*RATE)):
            t = i/RATE
            attack = min(1, t/.008)
            value = sum(a*math.exp(-t*d)*math.sin(math.tau*freq*m*t)
                        for m, a, d in ((1, 1, 3.2), (2.01, .35, 5.5), (3.02, .12, 8)))
            samples[offset+i] += attack*value
    peak = max(abs(x) for x in samples) or 1
    return b''.join(struct.pack('<h', int(x/peak*.85*32767)) for x in samples)

def ensure(folder):
    """Create any missing chime files and return {name: path}."""
    folder = Path(folder); folder.mkdir(parents=True, exist_ok=True)
    paths = {}
    for name, notes in CHIMES.items():
        path = folder/f'{name}.wav'
        if not path.exists():
            tmp = path.with_suffix('.tmp')
            with wave.open(str(tmp), 'wb') as f:
                f.setnchannels(1); f.setsampwidth(2); f.setframerate(RATE)
                f.writeframes(render(notes))
            tmp.replace(path)
        paths[name] = path
    return paths

def scaled(data, gain):
    """WAV bytes with every sample multiplied by gain (0..1); used for the volume setting."""
    import array, io
    with wave.open(io.BytesIO(data)) as src:
        params = src.getparams(); frames = array.array('h', src.readframes(src.getnframes()))
    for i, x in enumerate(frames): frames[i] = int(x*gain)
    out = io.BytesIO()
    with wave.open(out, 'wb') as dst:
        dst.setparams(params); dst.writeframes(frames.tobytes())
    return out.getvalue()

def play(data, gain):
    """Blocking playback through the Windows sound API (call from a worker thread)."""
    import winsound
    winsound.PlaySound(scaled(data, gain), winsound.SND_MEMORY)
