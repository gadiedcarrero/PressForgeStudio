"""Video LOCAL (image-to-video) con LTX-Video en ComfyUI. GRATIS en tu Mac.

Anima cada imagen de escena con movimiento sutil y natural. Más lento que fal,
pero $0. Usa el modelo LTX 2B distilled (8 pasos) por velocidad. Genera un clip
corto y lo repite en bucle "boomerang" (ida y vuelta, sin saltos) hasta cubrir
la duración de la escena, para que el movimiento no se congele.

Expone `image_to_video(...)` con la MISMA firma que el provider fal, para que el
pipeline elija uno u otro sin más cambios.
"""
from __future__ import annotations

import time
import uuid
from pathlib import Path

import httpx

from ..config import get_settings
from ..ffmpeg_utils import run_ffmpeg

_NEG = "worst quality, blurry, jittery, distorted, static, deformed, glitch, watermark"
_W, _H = 512, 768       # retrato; el render luego recorta a 9:16
_GEN_FRAMES = 57        # ~2.3 s a 25 fps · corto = rápido (luego se hace bucle)
_FPS = 25


def _parse_seconds(duration) -> float:
    try:
        return max(2.0, float(str(duration).strip()))
    except (TypeError, ValueError):
        return 5.0


class _LTXClient:
    def __init__(self) -> None:
        s = get_settings()
        self.base = s.comfyui_base_url.rstrip("/")
        self.model = s.comfyui_video_model
        self.t5 = s.comfyui_video_t5
        self.steps = s.comfyui_video_steps
        self.cfg = s.comfyui_video_cfg
        self._c = httpx.Client(timeout=1800.0)

    def _upload(self, image: Path) -> str:
        with open(image, "rb") as f:
            r = self._c.post(f"{self.base}/upload/image",
                             files={"image": (image.name, f, "image/png")},
                             data={"overwrite": "true"})
        r.raise_for_status()
        return r.json()["name"]

    def _workflow(self, ref_name: str, prompt: str, seed: int) -> dict:
        return {
            "1": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": self.model}},
            "14": {"class_type": "CLIPLoader", "inputs": {"clip_name": self.t5, "type": "ltxv"}},
            "2": {"class_type": "CLIPTextEncode", "inputs": {"text": prompt, "clip": ["14", 0]}},
            "3": {"class_type": "CLIPTextEncode", "inputs": {"text": _NEG, "clip": ["14", 0]}},
            "4": {"class_type": "LoadImage", "inputs": {"image": ref_name}},
            "5": {"class_type": "LTXVImgToVideo", "inputs": {
                "positive": ["2", 0], "negative": ["3", 0], "vae": ["1", 2], "image": ["4", 0],
                "width": _W, "height": _H, "length": _GEN_FRAMES, "batch_size": 1, "strength": 1.0}},
            "6": {"class_type": "LTXVConditioning", "inputs": {
                "positive": ["5", 0], "negative": ["5", 1], "frame_rate": float(_FPS)}},
            "7": {"class_type": "ModelSamplingLTXV", "inputs": {"model": ["1", 0], "max_shift": 2.05, "base_shift": 0.95}},
            "8": {"class_type": "LTXVScheduler", "inputs": {
                "steps": self.steps, "max_shift": 2.05, "base_shift": 0.95, "stretch": True, "terminal": 0.1}},
            "9": {"class_type": "KSamplerSelect", "inputs": {"sampler_name": "euler"}},
            "10": {"class_type": "SamplerCustom", "inputs": {
                "model": ["7", 0], "add_noise": True, "noise_seed": seed, "cfg": self.cfg,
                "positive": ["6", 0], "negative": ["6", 1], "sampler": ["9", 0],
                "sigmas": ["8", 0], "latent_image": ["5", 2]}},
            "11": {"class_type": "VAEDecode", "inputs": {"samples": ["10", 0], "vae": ["1", 2]}},
            "12": {"class_type": "CreateVideo", "inputs": {"images": ["11", 0], "fps": float(_FPS)}},
            "13": {"class_type": "SaveVideo", "inputs": {"video": ["12", 0], "filename_prefix": "pf_ltx", "format": "mp4", "codec": "h264"}},
        }

    def generate(self, image: Path, out_raw: Path, prompt: str) -> Path:
        ref = self._upload(image)
        seed = uuid.uuid4().int % (2 ** 32)
        r = self._c.post(f"{self.base}/prompt",
                         json={"prompt": self._workflow(ref, prompt, seed), "client_id": uuid.uuid4().hex})
        if r.status_code >= 400:
            raise RuntimeError(f"ComfyUI rechazó el workflow de video: {r.text[:300]}")
        pid = r.json()["prompt_id"]
        while True:
            h = self._c.get(f"{self.base}/history/{pid}").json()
            if pid in h:
                if (h[pid].get("status") or {}).get("status_str") == "error":
                    raise RuntimeError("ComfyUI falló animando (revisa su consola).")
                hist = h[pid]
                break
            time.sleep(2)
        for node in hist.get("outputs", {}).values():
            for v in (node.get("images") or node.get("video") or []):
                if isinstance(v, dict) and v.get("filename"):
                    resp = self._c.get(f"{self.base}/view", params={
                        "filename": v["filename"], "subfolder": v.get("subfolder", ""), "type": "output"})
                    resp.raise_for_status()
                    out_raw.parent.mkdir(parents=True, exist_ok=True)
                    out_raw.write_bytes(resp.content)
                    return out_raw
        raise RuntimeError("ComfyUI no devolvió el clip de video.")


def _boomerang_fill(src: Path, dst: Path, seconds: float) -> None:
    """Hace un bucle ida-y-vuelta (sin saltos) y lo repite hasta `seconds`."""
    loop = src.with_name(src.stem + "_bm.mp4")
    # ida + reverso concatenados = bucle perfecto para movimiento sutil
    run_ffmpeg(["-i", str(src), "-filter_complex",
                "[0]reverse[r];[0][r]concat=n=2:v=1[v]", "-map", "[v]", "-an", str(loop)])
    run_ffmpeg(["-stream_loop", "-1", "-i", str(loop), "-t", f"{seconds:.3f}",
                "-c:v", "libx264", "-pix_fmt", "yuv420p", str(dst)])
    loop.unlink(missing_ok=True)


def image_to_video(image, out_path, *, prompt: str, duration="5",
                   model: str | None = None, loop: bool = True, on_event=None) -> Path:
    """Anima una imagen con LTX local.

    loop=True  → bucle boomerang (ida y vuelta) hasta `duration` (para loops).
    loop=False → clip de una sola dirección (para reveals/acciones que no rebobinan).
    Firma compatible con providers.fal_video.image_to_video."""
    out_path = Path(out_path)
    if on_event:
        on_event("      (video local LTX: ~1 min en tu Mac…)")
    raw = out_path.with_name(out_path.stem + "_raw.mp4")
    _LTXClient().generate(Path(image), raw, prompt)
    if loop:
        _boomerang_fill(raw, out_path, _parse_seconds(duration))
    else:  # una sola dirección: re-encode el clip tal cual
        run_ffmpeg(["-i", str(raw), "-c:v", "libx264", "-pix_fmt", "yuv420p", str(out_path)])
    raw.unlink(missing_ok=True)
    return out_path
