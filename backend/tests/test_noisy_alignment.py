import numpy as np
import pytest
from scipy import signal
from app.alignment import estimate_offset, _waveform_offset


def music(seed=24, seconds=22, sr=8000):
    rng = np.random.default_rng(seed)
    out = np.zeros(seconds*sr)
    # Uneven musical events with changing pitches, harmonics and percussion.
    for onset in np.arange(.15, seconds-1, .23):
        start = int((onset+rng.uniform(-.05,.05))*sr)
        n = int(rng.uniform(.18,.65)*sr)
        t = np.arange(n)/sr
        f = rng.choice([164.81,196,220,261.63,293.66,329.63,392,440,523.25])
        note = (np.sin(2*np.pi*f*t)+.4*np.sin(4*np.pi*f*t)) * np.exp(-t*8)
        note += .15*rng.normal(size=n)*np.exp(-t*40)
        out[start:start+n] += note*rng.uniform(.2,.7)
    return out / max(np.max(np.abs(out)), 1)


def room(samples, sr=8000):
    # Nonlinear distortion, bandwidth/coloration, multiple reflections, background noise.
    sos = signal.butter(3, [250, 2400], fs=sr, btype='bandpass', output='sos')
    z = signal.sosfilt(sos, np.tanh(samples*5))
    z = z + .55*np.pad(z[:-280],(280,0)) + .3*np.pad(z[:-640],(640,0))
    rng=np.random.default_rng(81)
    return z + rng.normal(0,np.std(z)*.7,len(z))


@pytest.mark.parametrize('offset',[-2.137,1.373])
def test_room_recording(offset):
    clean=music()
    noisy=room(clean)
    a=32000
    b=a-round(offset*8000)
    ref=clean[a:a+96000]
    comp=noisy[b:b+104000]
    found, confidence=estimate_offset(ref,comp)
    assert abs(found-offset) < .04, (found,offset,confidence)
    assert 0 < confidence <= 1


def test_unrelated_music():
    with pytest.raises(ValueError,match='No reliable'):
        estimate_offset(music(1),room(music(90)))


def test_feature_only_when_waveform_unavailable(monkeypatch):
    import app.alignment as alignment
    def rejected(*args, **kwargs):
        raise ValueError('No waveform match')
    monkeypatch.setattr(alignment, '_waveform_offset', rejected)
    song=music()
    recorded=room(song)
    offset=1.373
    a=32000
    b=a-round(offset*8000)
    found, confidence=alignment.estimate_offset(song[a:a+96000],recorded[b:b+104000])
    assert abs(found-offset)<.04
    assert 0 < confidence < .65  # Accepted with warning, not rejected.


def test_noisy_export(tmp_path):
    from test_alignment import make_video
    from app.alignment import align_pair, probe
    song=music()
    recorded=room(song)
    a=32000
    offset=1.373
    b=a-round(offset*8000)
    ref, comp=tmp_path/'reference.mp4',tmp_path/'comparison.mp4'
    make_video(ref,song[a:a+96000],24)
    make_video(comp,recorded[b:b+104000],30)
    result=align_pair(ref,comp,tmp_path)
    assert abs(result['offset_seconds']-offset)<.04
    assert result['warnings']
    assert (tmp_path/'alignment.json').is_file()
    for name in ['reference_aligned.mp4','comparison_aligned.mp4']:
        assert probe(tmp_path/name)['fps']==30


@pytest.mark.parametrize('scale', [.95, 1.05])
def test_speed_mapping(scale):
    from app.alignment import estimate_mapping
    song=music(seconds=22)
    reference=song[16000:128000]
    comparison=signal.resample(room(song), round(len(song)*scale))
    offset, found_scale, confidence=estimate_mapping(reference, comparison)
    assert abs(found_scale-scale)<.005
    assert abs(offset-2*scale)<.06
    assert 0 < confidence <= 1
