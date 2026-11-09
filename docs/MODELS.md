# Models: what is installed and what is recommended
(kept by the assistant inside the AI Broker; updated, never rewritten from scratch)

## Installed (seen in C:\Migrated\AI\ComfyUI-Easy-Install, checked 2026-11-09)
- Image: Z-Image Turbo fp8 (checkpoints/z-image), Juggernaut Reborn (SD 1.5)
- Image edit: Qwen Image Edit 2509 lightning (nunchaku fp4), Qwen 2.5 VL 7B text encoder
- Video: Wan 2.2 TI2V 5B fp16
- 3D: Hunyuan 3D v2.1
- Music: ACE-Step 1.5 turbo
- ControlNet SD 1.5 (canny, depth, openpose), SEEDVR2 upscaler VAE

## Recommended next (checked 2026-11-09, not downloaded)
- FLUX.2 klein 4B (image): Apache 2.0, about 13 GB VRAM per BFL. Fits 16 GB but tight with display and games. Overlaps with Z-Image Turbo, so only a second opinion. Size not yet confirmed.
- TRELLIS.2-4B (image to 3D): MIT per official model card. VRAM unclear (sources say 16 to 24 GB), and one source says Windows is not officially supported. Overlaps with Hunyuan 3D 2.1. Check first, do not download yet.
- LTX-2 (video): NOT recommended. Lightricks licence has a revenue limit, which breaks the rules.
