"""ImageProvider local con ComfyUI (gratis, corre en tu Mac · Apple Silicon).

Genera imágenes con SDXL sin coste de API. Si se pasa una imagen de referencia
de un personaje, usa **InstantID** para mantener la MISMA cara en cada escena
(consistencia entre tomas del reel). Habla con un servidor ComfyUI por su API
HTTP; arráncalo aparte (ver docs) y deja `IMAGE_PROVIDER=local` en el .env.

Encaja con la interfaz de ImageProvider: generate(prompt, out_path, reference).
"""
from __future__ import annotations

import time
import uuid
from pathlib import Path

import httpx

from ..config import get_settings
from .base import ImageBlockedError

# Refuerzos de calidad y negativos típicos de SDXL (el prompt de escena ya viene
# detallado desde el guionista; aquí solo empujamos calidad/realismo).
_QUALITY = ("masterpiece, best quality, highly detailed, sharp focus, "
            "cinematic lighting, photorealistic, film still, 8k")
_NEGATIVE = ("lowres, bad anatomy, bad hands, extra fingers, missing fingers, "
             "deformed, mutated, blurry, watermark, text, signature, logo, "
             "cartoon, 3d render, cgi, disfigured, extra limbs, cloned face, "
             "duplicate, ugly, jpeg artifacts")

# Retrato SDXL (2:3); el render luego recorta a 9:16 (1080×1920).
_W, _H = 832, 1216


class ComfyUIImageProvider:
    """Cliente del API de ComfyUI. Dos caminos: txt2img normal, o InstantID
    (con foto de referencia) para fijar la cara del personaje."""

    # El pipeline lo usa para activar la consistencia automática (retrato maestro
    # por personaje → InstantID en cada escena).
    identity_reference = True

    def __init__(self) -> None:
        s = get_settings()
        self.base = s.comfyui_base_url.rstrip("/")
        self.ckpt = s.comfyui_checkpoint
        self.steps = s.comfyui_steps
        self.cfg = s.comfyui_cfg
        self.iid_weight = s.instantid_weight
        self._client = httpx.Client(timeout=900.0)  # generar en Mac puede tardar

    # ─── API de ComfyUI ───
    def _post_prompt(self, workflow: dict) -> str:
        r = self._client.post(f"{self.base}/prompt",
                              json={"prompt": workflow, "client_id": uuid.uuid4().hex})
        if r.status_code >= 400:
            raise RuntimeError(f"ComfyUI rechazó el workflow: {r.text[:300]}")
        return r.json()["prompt_id"]

    def _wait(self, prompt_id: str) -> dict:
        while True:
            r = self._client.get(f"{self.base}/history/{prompt_id}")
            r.raise_for_status()
            hist = r.json()
            if prompt_id in hist:
                entry = hist[prompt_id]
                status = (entry.get("status") or {}).get("status_str")
                if status == "error":
                    raise RuntimeError("ComfyUI falló al generar (revisa su consola).")
                return entry
            time.sleep(1.0)

    def _fetch_image(self, hist: dict, out_path: Path) -> Path:
        for node in hist.get("outputs", {}).values():
            for img in node.get("images", []):
                r = self._client.get(f"{self.base}/view", params={
                    "filename": img["filename"],
                    "subfolder": img.get("subfolder", ""),
                    "type": img.get("type", "output"),
                })
                r.raise_for_status()
                out_path.parent.mkdir(parents=True, exist_ok=True)
                out_path.write_bytes(r.content)
                return out_path
        raise RuntimeError("ComfyUI no devolvió ninguna imagen.")

    def _upload(self, image: Path) -> str:
        with open(image, "rb") as f:
            r = self._client.post(f"{self.base}/upload/image",
                                  files={"image": (image.name, f, "image/png")},
                                  data={"overwrite": "true"})
        r.raise_for_status()
        return r.json()["name"]

    # ─── Workflows (formato API de ComfyUI: id → {class_type, inputs}) ───
    def _txt2img(self, prompt: str, seed: int) -> dict:
        return {
            "4": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": self.ckpt}},
            "6": {"class_type": "CLIPTextEncode", "inputs": {"text": prompt, "clip": ["4", 1]}},
            "7": {"class_type": "CLIPTextEncode", "inputs": {"text": _NEGATIVE, "clip": ["4", 1]}},
            "5": {"class_type": "EmptyLatentImage", "inputs": {"width": _W, "height": _H, "batch_size": 1}},
            "3": {"class_type": "KSampler", "inputs": {
                "seed": seed, "steps": self.steps, "cfg": self.cfg,
                "sampler_name": "dpmpp_2m", "scheduler": "karras", "denoise": 1.0,
                "model": ["4", 0], "positive": ["6", 0], "negative": ["7", 0], "latent_image": ["5", 0]}},
            "8": {"class_type": "VAEDecode", "inputs": {"samples": ["3", 0], "vae": ["4", 2]}},
            "9": {"class_type": "SaveImage", "inputs": {"images": ["8", 0], "filename_prefix": "pf"}},
        }

    def _instantid(self, prompt: str, ref_name: str, seed: int) -> dict:
        return {
            "4": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": self.ckpt}},
            "11": {"class_type": "InstantIDModelLoader", "inputs": {"instantid_file": "ip-adapter.bin"}},
            "38": {"class_type": "InstantIDFaceAnalysis", "inputs": {"provider": "CPU"}},
            "16": {"class_type": "ControlNetLoader", "inputs": {"control_net_name": "instantid_controlnet.safetensors"}},
            "13": {"class_type": "LoadImage", "inputs": {"image": ref_name}},
            "6": {"class_type": "CLIPTextEncode", "inputs": {"text": prompt, "clip": ["4", 1]}},
            "7": {"class_type": "CLIPTextEncode", "inputs": {"text": _NEGATIVE, "clip": ["4", 1]}},
            "60": {"class_type": "ApplyInstantID", "inputs": {
                "instantid": ["11", 0], "insightface": ["38", 0], "control_net": ["16", 0],
                "image": ["13", 0], "model": ["4", 0], "positive": ["6", 0], "negative": ["7", 0],
                "weight": self.iid_weight, "start_at": 0.0, "end_at": 1.0}},
            "5": {"class_type": "EmptyLatentImage", "inputs": {"width": _W, "height": _H, "batch_size": 1}},
            "3": {"class_type": "KSampler", "inputs": {
                "seed": seed, "steps": self.steps, "cfg": self.cfg,
                "sampler_name": "dpmpp_2m", "scheduler": "karras", "denoise": 1.0,
                "model": ["60", 0], "positive": ["60", 1], "negative": ["60", 2], "latent_image": ["5", 0]}},
            "8": {"class_type": "VAEDecode", "inputs": {"samples": ["3", 0], "vae": ["4", 2]}},
            "9": {"class_type": "SaveImage", "inputs": {"images": ["8", 0], "filename_prefix": "pf"}},
        }

    # ─── Interfaz ImageProvider ───
    def generate(self, prompt: str, out_path: Path, reference: Path | None = None) -> Path:
        seed = uuid.uuid4().int % (2 ** 32)
        full = prompt.strip() + ", " + _QUALITY
        try:
            if reference and Path(reference).is_file():
                ref_name = self._upload(Path(reference))
                workflow = self._instantid(full, ref_name, seed)
            else:
                workflow = self._txt2img(full, seed)
            prompt_id = self._post_prompt(workflow)
            hist = self._wait(prompt_id)
            return self._fetch_image(hist, out_path)
        except httpx.HTTPError as exc:
            raise RuntimeError(
                f"No pude hablar con ComfyUI en {self.base}. "
                f"¿Está abierto? Arráncalo y reintenta. ({exc})"
            ) from exc

    def generate_with_refs(self, prompt: str, refs: list[Path], out_path: Path) -> Path:
        """Crea una imagen usando la primera referencia válida (misma cara)."""
        ref = next((r for r in refs if r and Path(r).is_file()), None)
        return self.generate(prompt, out_path, reference=ref)
