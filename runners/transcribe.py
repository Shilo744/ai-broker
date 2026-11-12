"""Speech to text with speakers, for the broker's `ivrit_transcribe` job type.
Transcription: faster-whisper with a CTranslate2 model (ivrit.ai Whisper large-v3 turbo). Speakers: sherpa-onnx (pyannote segmentation 3.0 + 3D-Speaker embeddings, both ONNX, no account,
no torch); every transcribed sentence gets the speaker who talks most during it.

  transcribe.py --audio <file> (--model <folder> | --model-small <folder> --model-large <folder> --size small|large) --outdir <folder> [--language he] [--device auto|cuda|cpu]
                [--diar-seg <segmentation model.onnx>] [--diar-emb <embedding .onnx>] [--speakers 0] [--dll-dir <folder with cudnn dlls>]

--speakers 0 = find the number of speakers by itself; N = exactly N. Without --diar-seg/--diar-emb (or if they are missing) it transcribes without speakers.
Writes transcript.txt (one paragraph per speaker turn), transcript.srt, transcript.json and speaker_N.wav (a sample of each voice) into the output folder.
Progress: lines "PROGRESS <percent> <text>" in the output (the window draws a real bar from them).
Exit codes: 0 ok, 2 bad input (file or model folder missing), 3 a needed package is not installed in this Python."""
import argparse
import json
import os
import sys


def _load_fmt():
    import importlib.util
    here = os.path.dirname(os.path.abspath(__file__))
    spec = importlib.util.spec_from_file_location("transcript_fmt", os.path.join(os.path.dirname(here), "aibroker", "transcript_fmt.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


fmt = _load_fmt()


def add_dlls(extra):
    """CUDA libraries on Windows: the nvidia-cublas wheel installed beside faster-whisper, plus an optional folder that has cuDNN 9."""
    if os.name != "nt":
        return
    for base in sys.path:
        d = os.path.join(base, "nvidia", "cublas", "bin")
        if os.path.isdir(d):
            os.add_dll_directory(d)
            os.environ["PATH"] = d + os.pathsep + os.environ.get("PATH", "")
    if extra and os.path.isdir(extra):
        os.add_dll_directory(extra)
        os.environ["PATH"] = extra + os.pathsep + os.environ.get("PATH", "")


def diarize(samples, seg, emb, n):
    import sherpa_onnx as so
    cfg = so.OfflineSpeakerDiarizationConfig(
        segmentation=so.OfflineSpeakerSegmentationModelConfig(pyannote=so.OfflineSpeakerSegmentationPyannoteModelConfig(model=seg), num_threads=4),
        embedding=so.SpeakerEmbeddingExtractorConfig(model=emb, num_threads=4),
        clustering=so.FastClusteringConfig(num_clusters=n if n > 0 else -1, threshold=0.9),
        min_duration_on=0.3, min_duration_off=0.5)
    sd = so.OfflineSpeakerDiarization(cfg)
    def tick(done, total, _arg=None):                       # 80-99 percent is the speaker separation
        print("PROGRESS %.0f separating speakers %d/%d" % (80 + 19.0 * done / max(total, 1), done, total), flush=True)
        return 0
    try:
        res = sd.process(samples, callback=tick).sort_by_start_time()
    except TypeError:                                       # an older sherpa-onnx without the callback
        res = sd.process(samples).sort_by_start_time()
    turns = [(r.start, r.end, r.speaker) for r in res]
    return turns if n > 0 else merge_small(turns)


def merge_small(turns, min_share=0.05):
    """When the number of speakers is not given, the clustering over-splits noisy recordings (a phone recording gave 21 'speakers' for about 4 people). A voice that talks less than
    min_share of all the speech is not a speaker of its own: each of its turns goes to the nearest turn in time of a main voice."""
    talk = {}
    for s, e, sp in turns:
        talk[sp] = talk.get(sp, 0.0) + (e - s)
    total = sum(talk.values()) or 1.0
    main = {sp for sp, t in talk.items() if t / total >= min_share}
    if not main or len(main) == len(talk):
        return turns
    mains = [(s, e, sp) for s, e, sp in turns if sp in main]
    out = []
    for s, e, sp in turns:
        if sp in main:
            out.append((s, e, sp))
            continue
        mid = (s + e) / 2
        near = min(mains, key=lambda m: 0 if m[0] <= mid <= m[1] else min(abs(mid - m[0]), abs(mid - m[1])))
        out.append((s, e, near[2]))
    return out


def speaker_of(turns, a, b):
    """The speaker with the most overlap with [a, b]; None when nobody speaks there."""
    best, over = None, 0.0
    for s, e, sp in turns:
        o = min(b, e) - max(a, s)
        if o > over:
            best, over = sp, o
    return best


def pick_samples(rows, turns, order, samples, outdir, per_speaker=6, max_len=8.0):
    """Short samples of every voice, so the owner can hear who is who and name them. In a conversation where people talk over each other a sample can be somebody else's words, so
    each speaker gets up to `per_speaker` different ones: the sentences with the least speech of OTHER speakers in them come first (longer ones before short ones), no two within 20 s
    of each other. Written as speaker_<id>_<k>.wav (16 kHz mono); the first one is also speaker_<id>.wav."""
    import wave
    import numpy as np
    mine = {sp: [(s, e, o) for s, e, o in turns if order.get(o) == sp] for sp in order.values()}

    def foreign(a, b, sp):
        """Seconds of [a, b] in which somebody else is speaking."""
        return sum(max(0.0, min(b, e) - max(a, s)) for other, ts in mine.items() if other != sp for s, e, _ in ts)

    out = []
    for sp in sorted(order.values()):
        cands = []
        for r in rows:
            if r["speaker"] != sp or r["end"] - r["start"] < 1.5:
                continue
            a, b = r["start"], min(r["end"], r["start"] + max_len)
            dirty = foreign(a, b, sp) / max(b - a, 0.1)
            cands.append((dirty > 0.1, round(dirty, 2), -(b - a), a, b, r["text"]))
        cands.sort()
        chosen = []
        for c in cands:
            if all(abs(c[3] - o[3]) >= 20 for o in chosen):
                chosen.append(c)
            if len(chosen) >= per_speaker:
                break
        if not chosen and any(r["speaker"] == sp for r in rows):        # only very short sentences: take the longest
            r = max((r for r in rows if r["speaker"] == sp), key=lambda r: r["end"] - r["start"])
            chosen = [(False, 0.0, 0.0, r["start"], min(r["end"], r["start"] + max_len), r["text"])]
        entry = {"id": sp, "samples": []}
        for k, (_d, dirty, _l, a, b, text) in enumerate(chosen, 1):
            name = "speaker_%d_%d.wav" % (sp, k)
            lo, hi = int(a * 16000), int(b * 16000)
            for fname in ((name, "speaker_%d.wav" % sp) if k == 1 else (name,)):
                with wave.open(os.path.join(outdir, fname), "wb") as w:
                    w.setnchannels(1)
                    w.setsampwidth(2)
                    w.setframerate(16000)
                    w.writeframes((np.clip(samples[lo:hi], -1, 1) * 32767).astype(np.int16).tobytes())
            entry["samples"].append({"file": name, "from": round(a, 1), "to": round(b, 1), "text": text, "overlap": dirty})
        entry["sample"] = "speaker_%d.wav" % sp
        out.append(entry)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--audio", required=True)
    ap.add_argument("--model", default="")                       # one model folder, or
    ap.add_argument("--model-small", default="")                 # --size picks between these two (large falls back to small when it is not installed)
    ap.add_argument("--model-large", default="")
    ap.add_argument("--size", default="large")
    ap.add_argument("--outdir", required=True)
    ap.add_argument("--language", default="he")
    ap.add_argument("--device", default="auto")
    ap.add_argument("--diar-seg", default="")
    ap.add_argument("--diar-emb", default="")
    ap.add_argument("--speakers", type=int, default=0)
    ap.add_argument("--dll-dir", default="")
    a = ap.parse_args()
    if not os.path.isfile(a.audio):
        print("audio file not found: %s" % a.audio)
        return 2
    if not a.model:
        want = a.model_large if a.size == "large" else a.model_small
        a.model = want if os.path.isfile(os.path.join(want or "", "model.bin")) else a.model_small
        if a.model != want:
            print("the %s model is not installed: using the small one" % a.size, flush=True)
    if not os.path.isfile(os.path.join(a.model, "model.bin")):
        print("model folder has no model.bin: %s" % a.model)
        return 2
    print("model: %s" % os.path.basename(a.model.rstrip("/\\")), flush=True)
    add_dlls(a.dll_dir)
    try:
        from faster_whisper import WhisperModel
        from faster_whisper.audio import decode_audio
    except ImportError:
        print("faster-whisper is not installed in this Python (pip install faster-whisper)")
        return 3
    samples = decode_audio(a.audio, sampling_rate=16000)
    seconds = len(samples) / 16000.0
    print("audio: %.0f s" % seconds, flush=True)
    device = a.device
    if device == "auto":
        try:
            import ctranslate2
            device = "cuda" if ctranslate2.get_cuda_device_count() > 0 else "cpu"
        except Exception:
            device = "cpu"
    try:
        model = WhisperModel(a.model, device=device, compute_type="float16" if device == "cuda" else "int8")
        segments, info = model.transcribe(samples, language=(a.language or None), vad_filter=True, beam_size=5)
        rows = []
        for s in segments:
            rows.append({"start": s.start, "end": s.end, "text": s.text.strip()})
            if len(rows) % 10 == 0:
                print("PROGRESS %.0f %.0f/%.0f s" % (min(80.0, 80.0 * s.end / max(seconds, 1.0)), s.end, seconds), flush=True)      # 0-80 percent is the transcription
    except Exception as e:
        if device != "cuda":
            raise
        print("GPU failed (%s); trying the CPU" % str(e)[:200], flush=True)
        device = "cpu"
        model = WhisperModel(a.model, device="cpu", compute_type="int8")
        segments, info = model.transcribe(samples, language=(a.language or None), vad_filter=True, beam_size=5)
        rows = [{"start": s.start, "end": s.end, "text": s.text.strip()} for s in segments]
    print("device: %s, %d sentences" % (device, len(rows)), flush=True)

    turns = []
    if a.diar_seg and a.diar_emb and os.path.isfile(a.diar_seg) and os.path.isfile(a.diar_emb):
        try:
            print("PROGRESS 80 separating speakers", flush=True)
            turns = diarize(samples, a.diar_seg, a.diar_emb, a.speakers)
        except ImportError:
            print("sherpa-onnx is not installed: no speaker separation")
        except Exception as e:
            print("speaker separation failed (%s): continuing without speakers" % str(e)[:200])
    order = {}
    for r in rows:
        sp = speaker_of(turns, r["start"], r["end"]) if turns else None
        if sp is not None and sp not in order:
            order[sp] = len(order) + 1                      # speakers are numbered in the order they first speak in the text
        r["speaker"] = order.get(sp)

    os.makedirs(a.outdir, exist_ok=True)
    spk = pick_samples(rows, turns, order, samples, a.outdir) if order else []
    fmt.write(a.outdir, {"language": a.language or info.language, "detected_language": info.language, "duration": seconds, "speakers": spk, "names": {}, "turns": [[round(t[0], 2), round(t[1], 2), order.get(t[2])] for t in turns if t[2] in order], "segments": rows})
    print("PROGRESS 100 done", flush=True)
    print("done: %d sentences, %d speakers, language %s, %.0f s of audio" % (len(rows), len(order), info.language, seconds))
    return 0


sys.exit(main())
