import json
from pathlib import Path
import subprocess
import time
import numpy as np
import pytest
from scipy.io.wavfile import write
from app.alignment import estimate_offset, align_pair, probe, audio_samples
from fastapi.testclient import TestClient
from app.main import app


def soundtrack(seconds=16, sr=8000):
    rng = np.random.default_rng(8)
    return rng.normal(0, .15, seconds*sr)


@pytest.mark.parametrize('offset', [-2.125, 0, 1.375])
def test_sign_and_noise(offset):
    song = soundtrack()
    start_ref = 24000
    start_comp = start_ref-round(offset*8000)
    ref = song[start_ref:start_ref+64000]
    comp = song[start_comp:start_comp+72000]*.6 + np.random.default_rng(2).normal(0,.008,72000)
    found, confidence = estimate_offset(ref, comp)
    assert found == pytest.approx(offset, abs=1/8000)
    assert confidence > .9


def test_silence_and_unrelated():
    with pytest.raises(ValueError, match='silent'):
        estimate_offset(np.zeros(32000), soundtrack(4))
    with pytest.raises(ValueError, match='No reliable'):
        estimate_offset(soundtrack(4), np.random.default_rng(77).normal(0,.1,32000))


def make_video(path, samples, fps):
    wav = path.with_suffix('.wav')
    write(wav, 8000, samples.astype('float32'))
    subprocess.run(['ffmpeg','-v','error','-y','-f','lavfi','-i',f'testsrc2=size=160x240:rate={fps}',
                    '-i',str(wav),'-t',str(len(samples)/8000),'-c:v','libx264','-pix_fmt','yuv420p','-c:a','aac',str(path)],check=True)


@pytest.mark.parametrize('offset', [-1.25, 1.375])
def test_real_exports(tmp_path, offset):
    song = soundtrack()
    rstart = 24000
    cstart = rstart-round(offset*8000)
    ref, comp = tmp_path/'reference.mp4', tmp_path/'comparison.mp4'
    make_video(ref,song[rstart:rstart+64000],24)
    make_video(comp,song[cstart:cstart+72000],60)
    result = align_pair(ref,comp,tmp_path)
    assert result['offset_seconds'] == pytest.approx(offset,abs=.003)
    assert result['overlap_start_ref'] == pytest.approx(max(0,-offset),abs=.003)
    assert result['overlap_end_ref'] == pytest.approx(min(8,9-offset),abs=.003)
    lengths = []
    for name in ['reference_aligned.mp4','comparison_aligned.mp4']:
        info=json.loads(subprocess.check_output(['ffprobe','-v','error','-select_streams','v:0','-count_frames','-show_entries','stream=avg_frame_rate,nb_read_frames,start_time','-of','json',str(tmp_path/name)]))['streams'][0]
        assert info['avg_frame_rate']=='30/1'
        assert float(info['start_time'])==0
        lengths.append(int(info['nb_read_frames']))
    assert lengths==[result['output_frames']]*2
    exported = [audio_samples(tmp_path/name,probe(tmp_path/name)) for name in ['reference_aligned.mp4','comparison_aligned.mp4']]
    residual,_=estimate_offset(*exported)
    assert abs(residual)<.005


def test_api(tmp_path, monkeypatch):
    import app.main as main
    monkeypatch.setattr(main,'ROOT',tmp_path/'jobs')
    main.ROOT.mkdir()
    song=soundtrack(5)
    reference=tmp_path/'r.mp4'
    make_video(reference,song,30)
    with TestClient(app) as client:
        assert client.post('/api/align').status_code==422
        assert client.post('/api/align',data={'reference_url':'https://localhost/a','comparison_url':'https://www.tiktok.com/@x/video/1'}).status_code==422
        with reference.open('rb') as a,reference.open('rb') as b:
            response=client.post('/api/align',files={'reference_file':('a.mp4',a,'video/mp4'),'comparison_file':('b.mp4',b,'video/mp4')})
        assert response.status_code==202
        for _ in range(200):
            status=client.get(response.json()['status_url']).json()
            if status['status'] in ('completed','failed'):break
            time.sleep(.1)
        assert status['status']=='completed',status
        assert status['result']['offset_seconds']==0
        for url in status['downloads'].values():
            assert client.get(url).status_code==200
        assert client.get('/api/jobs/not-a-job').status_code==404
