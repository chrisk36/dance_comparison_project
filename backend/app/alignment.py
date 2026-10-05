"""Constant-offset alignment. All time coordinates are relative to video start."""
import json
import math
import subprocess
from fractions import Fraction
from pathlib import Path
import numpy as np
from scipy import signal

SR = 8000
MAX_SECONDS = 180


def run(args, timeout=240):
    try:
        return subprocess.run(args, check=True, capture_output=True, timeout=timeout).stdout
    except subprocess.TimeoutExpired as exc:
        raise ValueError('Media processing timed out.') from exc
    except subprocess.CalledProcessError as exc:
        raise ValueError('Unable to decode or export this media. Use a playable MP4 with audio.') from exc


def probe(path):
    data = json.loads(run(['ffprobe', '-v', 'error', '-show_streams', '-show_format', '-of', 'json', str(path)]))
    video = next((s for s in data['streams'] if s['codec_type'] == 'video'), None)
    audio = next((s for s in data['streams'] if s['codec_type'] == 'audio'), None)
    if not video or not audio:
        raise ValueError('Both videos must contain video and audio streams.')
    duration = float(video.get('duration') or data['format'].get('duration', 0))
    if not 3 <= duration <= MAX_SECONDS:
        raise ValueError(f'Videos must be 3–{MAX_SECONDS} seconds long.')
    rate = video.get('avg_frame_rate', '0/1')
    fps = float(Fraction(rate)) if rate != '0/0' else 0
    if fps <= 0:
        fps = float(Fraction(video['r_frame_rate']))
    return {'duration': duration, 'fps': fps, 'video_start': float(video.get('start_time', 0)),
            'audio_start': float(audio.get('start_time', 0))}


def audio_samples(path, meta):
    raw = run(['ffmpeg', '-v', 'error', '-i', str(path), '-map', '0:a:0', '-t', str(MAX_SECONDS),
               '-ac', '1', '-ar', str(SR), '-f', 'f32le', 'pipe:1'])
    samples = np.frombuffer(raw, dtype='<f4').astype(np.float64)
    delay = round((meta['audio_start'] - meta['video_start']) * SR)
    samples = np.pad(samples, (max(delay, 0), 0))[max(-delay, 0):]
    length = round(meta['duration'] * SR)
    return np.pad(samples[:length], (0, max(0, length - len(samples))))


def _waveform_offset(reference, comparison, sr=SR):
    """Overlap-normalized FFT correlation; positive lag means comparison starts earlier."""
    x, y = np.asarray(reference, float), np.asarray(comparison, float)
    if min(len(x), len(y)) < 3 * sr:
        raise ValueError('At least three seconds of audio are required.')
    x = x - x.mean()
    y = y - y.mean()
    if min(np.sqrt(np.mean(x*x)), np.sqrt(np.mean(y*y))) < 1e-5:
        raise ValueError('One of the videos has silent audio.')
    # correlate(comparison, reference) gives the requested comparison-minus-reference lag.
    lags = signal.correlation_lags(len(y), len(x))
    r0 = np.maximum(0, -lags)
    r1 = np.minimum(len(x), len(y) - lags)
    c0, c1 = r0 + lags, r1 + lags
    n = r1 - r0
    px, py = np.r_[0., np.cumsum(x*x)], np.r_[0., np.cumsum(y*y)]
    energy = np.sqrt(np.maximum((px[r1]-px[r0]) * (py[c1]-py[c0]), 0))
    scores = np.abs(signal.correlate(y, x, method='fft')) / np.maximum(energy, 1e-12)
    valid = (n >= max(3*sr, int(.25*min(len(x), len(y))))) & (energy > 1e-8)
    scores[~valid] = 0
    best = int(np.argmax(scores))
    peak = float(np.clip(scores[best], 0, 1))
    if peak < .18:
        raise ValueError('No reliable shared audio found. Try clips with the same unedited soundtrack.')
    # Penalize competing peaks outside a 100ms neighborhood (repeated sections/periodicity).
    other = scores.copy()
    other[np.abs(lags-lags[best]) <= int(.1*sr)] = 0
    runner = float(other.max())
    uniqueness = np.clip((peak-runner)/max(peak*.5, 1e-9), 0, 1)
    confidence = float(np.clip(peak * (.5 + .5*uniqueness), 0, 1))
    return float(lags[best]/sr), confidence


def _features(samples, sr):
    """32 normalized log-mel bands, with a 10 ms time step; no new dependencies."""
    from scipy.ndimage import gaussian_filter1d
    hop = max(1, round(sr * .01))
    nfft = 2 ** int(np.ceil(np.log2(sr * .064)))
    frequencies, _, stft = signal.stft(samples, fs=sr, nperseg=nfft,
                                      noverlap=nfft-hop, boundary='zeros', padded=False)
    mel = lambda hz: 2595 * np.log10(1 + hz / 700)
    edges = 700 * (10 ** (np.linspace(mel(100), mel(min(3800, sr*.48)), 34)/2595)-1)
    filters = np.maximum(0, np.minimum(
        (frequencies[None, :] - edges[:-2, None]) / np.diff(edges)[:-1, None],
        (edges[2:, None] - frequencies[None, :]) / np.diff(edges)[1:, None]))
    power = filters @ (np.abs(stft)**2)
    logmel = np.log(np.maximum(power, max(float(power.max())*1e-7, 1e-15)))
    # Remove slow background/recording response; retain changing musical patterns.
    features = logmel - gaussian_filter1d(logmel, sigma=.4*sr/hop, axis=1)
    scale = np.std(features, axis=1, keepdims=True)
    features = np.clip(features / np.maximum(scale, .15), -3, 3)
    return features, hop/sr


def _feature_curve(x, y, min_frames):
    lags = signal.correlation_lags(y.shape[1], x.shape[1])
    r0, r1 = np.maximum(0, -lags), np.minimum(x.shape[1], y.shape[1]-lags)
    c0, c1 = r0+lags, r1+lags
    ex = np.r_[0., np.cumsum(np.sum(x*x, axis=0))]
    ey = np.r_[0., np.cumsum(np.sum(y*y, axis=0))]
    norm = np.sqrt(np.maximum((ex[r1]-ex[r0])*(ey[c1]-ey[c0]), 0))
    cross = sum(signal.correlate(b, a, method='fft') for a, b in zip(x, y))
    scores = cross / np.maximum(norm, 1e-12)
    scores[(r1-r0 < min_frames) | (norm < 1e-8)] = -1
    return lags, scores


def estimate_offset(reference, comparison, sr=SR):
    """Hybrid exact-waveform / noise-robust feature matching with unchanged API.

    The score is heuristic, not a probability. Weak but corroborated feature
    matches export with a warning; unrelated or ambiguous patterns are rejected.
    """
    x, y = np.asarray(reference, float), np.asarray(comparison, float)
    if x.ndim != 1 or y.ndim != 1 or not np.isfinite(x).all() or not np.isfinite(y).all():
        raise ValueError('Audio must contain finite mono samples.')
    if min(len(x), len(y)) < 3*sr:
        raise ValueError('At least three seconds of audio are required.')
    x, y = x-x.mean(), y-y.mean()
    if min(np.std(x), np.std(y)) < 1e-5:
        raise ValueError('One of the videos has silent audio.')
    # Preserve sample-level precision for clean/shared digital soundtracks.
    wave = None
    try:
        wave = _waveform_offset(x, y, sr)
        if wave[1] >= .70:
            return wave
    except ValueError:
        pass
    fx, step = _features(x, sr)
    fy, _ = _features(y, sr)
    minimum = max(round(3/step), int(.25*min(fx.shape[1], fy.shape[1])))
    lags, scores = _feature_curve(fx, fy, minimum)
    best = int(np.argmax(scores))
    peak, lag = float(scores[best]), int(lags[best])
    alternatives = scores.copy()
    alternatives[np.abs(lags-lag)*step < .30] = -1
    runner = max(0., float(alternatives.max()))
    margin = peak-runner
    # Corroborate the proposed offset in three disjoint sections.
    r0, r1 = max(0, -lag), min(fx.shape[1], fy.shape[1]-lag)
    section_scores = []
    for indices in np.array_split(np.arange(r0, r1), 3):
        a, b = fx[:, indices], fy[:, indices+lag]
        section_scores.append(float(np.sum(a*b)/max(np.linalg.norm(a)*np.linalg.norm(b), 1e-12)))
    support = sum(v >= .12 for v in section_scores)
    if peak < .20 or margin < .035 or support < 2:
        raise ValueError('No reliable shared musical pattern found. Try a longer clip with clearer music at the same playback speed.')
    # Parabolic peak interpolation gives a sub-hop estimate, not sample accuracy.
    delta = 0.
    if 0 < best < len(scores)-1:
        left, right = scores[best-1], scores[best+1]
        denominator = left-2*peak+right
        if denominator < -1e-9:
            delta = float(np.clip(.5*(left-right)/denominator, -.5, .5))
    offset = (lag+delta)*step
    if wave is not None and abs(wave[0]-offset) < .05:
        offset = wave[0]
    uniqueness = float(np.clip(margin/.20, 0, 1))
    confidence = float(np.clip(peak*(.6+.4*uniqueness)*(support/3), 0, 1))
    return float(offset), confidence


def estimate_mapping(reference, comparison, sr=SR):
    """Fit comparison_time = offset + scale * reference_time when drift exists."""
    try:
        offset, confidence = estimate_offset(reference, comparison, sr)
        constant = (offset, 1., confidence)
    except ValueError:
        constant = None
    fx, step = _features(reference, sr)
    fy, _ = _features(comparison, sr)
    window = round(3/step)
    points = []
    for start in range(0, fx.shape[1]-window+1, window//2):
        lags, scores = _feature_curve(fx[:, start:start+window], fy, window)
        best = int(scores.argmax())
        other = scores.copy()
        other[np.abs(lags-lags[best])*step < .3] = -1
        if scores[best] >= .25 and scores[best]-other.max() >= .045:
            points.append(((start+window/2)*step, (lags[best]+window/2)*step, scores[best]))
    if len(points) < 4:
        if constant is not None:
            return constant
        raise ValueError('Not enough consistent musical sections to align these clips.')
    pts = np.array(points)
    # Deterministic robust consensus: outlying/repeated song sections cannot set the mapping.
    best_mask = None
    for i in range(len(pts)):
        for j in range(i+1,len(pts)):
            scale = (pts[j,1]-pts[i,1])/(pts[j,0]-pts[i,0])
            if not .85 <= scale <= 1.15:
                continue
            offset = pts[i,1]-scale*pts[i,0]
            mask = np.abs(pts[:,1]-(offset+scale*pts[:,0])) < .085
            if best_mask is None or mask.sum() > best_mask.sum():
                best_mask = mask
    if best_mask is None or best_mask.sum() < max(4, int(np.ceil(.7*len(pts)))):
        if constant is not None:
            return constant
        raise ValueError('Music matches locally but timing is inconsistent across the video.')
    good = pts[best_mask]
    if np.ptp(good[:,0]) < .5*(len(reference)/sr):
        if constant is not None:
            return constant
        raise ValueError('Music match does not cover enough of the reference.')
    scale, offset = np.polyfit(good[:,0], good[:,1], 1)
    residual = float(np.sqrt(np.mean((good[:,1]-(offset+scale*good[:,0]))**2)))
    if abs(scale-1) < .003 and constant is not None:
        return constant
    # Re-score the entire reference against speed-corrected comparison audio.
    corrected = signal.resample(comparison, round(len(comparison)/scale))
    try:
        refined, confidence = estimate_offset(reference, corrected, sr)
    except ValueError as exc:
        if constant is not None:
            return constant
        raise ValueError('Local matches could not be confirmed across the speed-corrected audio.') from exc
    if abs(refined*scale-offset) > .15:
        raise ValueError('Conflicting audio matches; cannot safely choose a segment.')
    return float(refined*scale), float(scale), float(confidence * np.exp(-residual/.15))


def align_pair(reference: Path, comparison: Path, directory: Path):
    rm, cm = probe(reference), probe(comparison)
    offset, scale, confidence = estimate_mapping(audio_samples(reference, rm), audio_samples(comparison, cm))
    start = max(0., -offset/scale)
    end = min(rm['duration'], (cm['duration'] - offset)/scale)
    frames = math.floor((end-start)*30 + 1e-8)
    if frames < 90:
        raise ValueError('Less than three seconds of shared video content.')
    duration = frames/30
    outputs = [directory/'reference_aligned.mp4', directory/'comparison_aligned.mp4']
    filters = []
    for i, (meta, trim_start) in enumerate([(rm, start), (cm, start*scale+offset)]):
        # Use the original video origin for both streams, preserving audio/video stream delay.
        origin = meta['video_start']
        speed = 1. if i == 0 else scale
        source_duration = duration*speed
        filters += [f'[{i}:v:0]setpts=PTS-{origin}/TB,trim=start={trim_start}:duration={source_duration},setpts=(PTS-{trim_start}/TB)/{speed},fps=30:start_time=0,tpad=stop_mode=clone:stop_duration=0.1,trim=end_frame={frames},scale=trunc(iw/2)*2:trunc(ih/2)*2[v{i}]',
                    f'[{i}:a:0]asetpts=PTS-{origin}/TB,atrim=start={trim_start}:duration={source_duration},asetpts=PTS-{trim_start}/TB,atempo={speed},aresample=async=1:first_pts=0,apad,atrim=duration={duration}[a{i}]']
    command = ['ffmpeg', '-v', 'error', '-y', '-copyts', '-i', str(reference), '-i', str(comparison), '-filter_complex', ';'.join(filters)]
    for i, output in enumerate(outputs):
        command += ['-map', f'[v{i}]', '-map', f'[a{i}]', '-c:v', 'libx264', '-preset', 'fast', '-crf', '20', '-pix_fmt', 'yuv420p', '-c:a', 'aac', '-ar', '48000', '-movflags', '+faststart', str(output)]
    run(command)
    result = {'reference_video': str(reference.resolve()), 'comparison_video': str(comparison.resolve()),
              'offset_seconds': offset, 'comparison_time_scale': scale,
              'time_mapping': 'comparison_time = reference_time * comparison_time_scale + offset_seconds',
              'comparison_start_seconds': start*scale+offset, 'comparison_end_seconds': (start+duration)*scale+offset, 'overlap_start_ref': start, 'overlap_end_ref': end,
              'reference_fps': rm['fps'], 'comparison_fps': cm['fps'], 'alignment_confidence': round(confidence, 6),
              'reference_aligned_video': str(outputs[0].resolve()), 'comparison_aligned_video': str(outputs[1].resolve()),
              'output_fps': 30, 'output_frames': frames, 'output_duration_seconds': duration,
              'export_end_ref': start+duration,
              'warnings': (['Comparison playback speed corrected to match the reference.'] if abs(scale-1) >= .003 else []) + (['Audio pattern matched with limited confidence; review synchronization before ranking.'] if confidence < .65 else [])}
    (directory/'alignment.json').write_text(json.dumps(result, indent=2))
    return result
