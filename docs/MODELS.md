# Models: what is installed and what is recommended
(kept by the assistant inside the AI Broker; updated, never rewritten from scratch)

## Installed (seen in C:\Migrated\AI\ComfyUI-Easy-Install, checked 2026-11-09)
- Image: Z-Image Turbo fp8 (checkpoints/z-image), Juggernaut Reborn (SD 1.5)
- Image edit: Qwen Image Edit 2509 lightning (nunchaku fp4), Qwen 2.5 VL 7B text encoder
- Video: Wan 2.2 TI2V 5B fp16
- 3D: Hunyuan 3D v2.1
- Music: ACE-Step 1.5 turbo
- ControlNet SD 1.5 (canny, depth, openpose), SEEDVR2 upscaler VAE

## Downloaded 2026-11-12 (files may still be in progress; check the download log before use)
- FLUX.2 klein 4B fp8 (image create and edit), Apache-2.0, 4.07 GB, in ComfyUI diffusion_models. Not yet tested on this machine; measure its VRAM and time with one job before relying on it.
- ivrit.ai Whisper large-v3 turbo (Hebrew transcription), Apache-2.0, 1.51 GB, in ai-broker models\whisper. No transcription job type exists in the broker yet, so it cannot run from the broker.
- Both are now entries in `catalog/packs.json` (ids `flux2_klein` and `ivrit_transcribe`) with preview pictures in `catalog/thumbs/`, so the program's model list shows them as installed. Neither has a job type yet.
- Not downloaded: pyannote (speaker separation). It needs a Hugging Face account and accepting terms, which the owner did not approve.

## Recommended next (checked 2026-11-09, not downloaded)
- TRELLIS.2-4B (image to 3D): MIT per official model card. VRAM unclear (sources say 16 to 24 GB), and one source says Windows is not officially supported. Overlaps with Hunyuan 3D 2.1. Check first, do not download yet.
- LTX-2 (video): NOT recommended. Lightricks licence has a revenue limit, which breaks the rules.
