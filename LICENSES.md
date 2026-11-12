# Licences of what AI Broker uses
| Part | Licence | Note |
|---|---|---|
| PySide6 / Qt 6 (pip, unmodified, dynamic) | LGPL-3.0 | internal tool, not redistributed |
| psutil | BSD-3 | |
| mcp (Model Context Protocol Python SDK) | MIT | plus its dependencies (pydantic MIT, httpx BSD, starlette BSD, uvicorn BSD ...) |
| Broker code, job types, runners, skill | owner's | |
Job types call tools the owner already has (ComfyUI, TripoSG MIT, Step1X Apache-2.0, Blender GPL as a separate program, Godot MIT); their licences are the owner's existing ones.
| faster-whisper, ctranslate2 | MIT | transcription environment only |
| sherpa-onnx | Apache-2.0 | speaker separation, same environment |
| pyannote segmentation 3.0 (ONNX export) | MIT | (c) CNRS; no Hugging Face account needed from the sherpa-onnx release |
| 3D-Speaker ERes2Net speaker embedding | Apache-2.0 per the project, not verified on the model card | check before any redistribution |
| ivrit.ai Whisper large-v3 turbo | Apache-2.0 (training-data terms separate, not read) | |
