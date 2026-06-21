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

# Refuerzo de calidad NEUTRO (sin sesgar a realismo, para que el ESTILO elegido
# —anime, 3D, pintura…— mande). El look concreto lo pone _style_suffix().
_QUALITY = "masterpiece, best quality, highly detailed, sharp focus, 8k"


# Estilos cuyo modelo deforma caras con el acelerador Lightning → pasos completos.
_NO_LIGHTNING_STYLES = {"anime"}


def _style_key() -> str:
    from ..secrets_store import get_secret
    from .openai_image import DEFAULT_STYLE
    return (get_secret("image_style") or DEFAULT_STYLE).strip()


def _style_suffix(key: str | None = None) -> str:
    """Texto del 'Estilo visual'. Si se pasa `key`, fuerza ese estilo (lo usa
    Skybot para un look cinematográfico fijo); si no, usa el elegido en la UI."""
    from .openai_image import STYLES, DEFAULT_STYLE
    return STYLES.get(key or _style_key(), STYLES[DEFAULT_STYLE])
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
        # Estilos no realistas → modelo especializado (el resto usa RealVisXL).
        self._style_ckpts = {}
        if (s.comfyui_anime_checkpoint or "").strip():
            self._style_ckpts["anime"] = s.comfyui_anime_checkpoint.strip()
        if (s.comfyui_3d_checkpoint or "").strip():
            self._style_ckpts["3d"] = s.comfyui_3d_checkpoint.strip()
        self.lightning = (s.comfyui_lightning_lora or "").strip()
        self.steps = s.comfyui_steps
        self.cfg = s.comfyui_cfg
        self.iid_weight = s.instantid_weight
        self.iid_end = s.instantid_end_at
        self._style_ov: str | None = None  # override de estilo por llamada (Skybot)
        self._client = httpx.Client(timeout=900.0)  # generar en Mac puede tardar

    def _skey(self) -> str:
        return self._style_ov or _style_key()

    def _checkpoint(self) -> str:
        """Modelo según el estilo: anime → Animagine, 3d → RealCartoon-XL;
        el resto → RealVisXL (fotográfico)."""
        return self._style_ckpts.get(self._skey(), self.ckpt)

    def _use_lightning(self) -> bool:
        # Lightning acelera, pero deforma caras en algunos modelos (Animagine):
        # esos estilos van a pasos completos.
        return bool(self.lightning) and self._skey() not in _NO_LIGHTNING_STYLES

    def _sampling(self) -> tuple[int, float, str, str]:
        """(steps, cfg, sampler, scheduler) según si usa Lightning o calidad full."""
        if self._use_lightning():
            return self.steps, self.cfg, "euler", "sgm_uniform"
        return 28, 5.0, "dpmpp_2m", "karras"

    def _base_nodes(self) -> tuple[dict, list, list, list]:
        """Nodos comunes (checkpoint + LoRA Lightning opcional). Devuelve el dict
        de nodos y las referencias [model, clip, vae] a encadenar."""
        nodes = {"4": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": self._checkpoint()}}}
        model, clip, vae = ["4", 0], ["4", 1], ["4", 2]
        if self._use_lightning():
            nodes["10"] = {"class_type": "LoraLoader", "inputs": {
                "lora_name": self.lightning, "strength_model": 1.0, "strength_clip": 1.0,
                "model": ["4", 0], "clip": ["4", 1]}}
            model, clip = ["10", 0], ["10", 1]
        return nodes, model, clip, vae

    def _sampler(self, seed: int, model, positive, negative) -> dict:
        steps, cfg, sampler, scheduler = self._sampling()
        return {"class_type": "KSampler", "inputs": {
            "seed": seed, "steps": steps, "cfg": cfg,
            "sampler_name": sampler, "scheduler": scheduler, "denoise": 1.0,
            "model": model, "positive": positive, "negative": negative, "latent_image": ["5", 0]}}

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
        nodes, model, clip, vae = self._base_nodes()
        nodes.update({
            "6": {"class_type": "CLIPTextEncode", "inputs": {"text": prompt, "clip": clip}},
            "7": {"class_type": "CLIPTextEncode", "inputs": {"text": _NEGATIVE, "clip": clip}},
            "5": {"class_type": "EmptyLatentImage", "inputs": {"width": _W, "height": _H, "batch_size": 1}},
            "3": self._sampler(seed, model, ["6", 0], ["7", 0]),
            "8": {"class_type": "VAEDecode", "inputs": {"samples": ["3", 0], "vae": vae}},
            "9": {"class_type": "SaveImage", "inputs": {"images": ["8", 0], "filename_prefix": "pf"}},
        })
        return nodes

    def _instantid(self, prompt: str, ref_name: str, seed: int) -> dict:
        nodes, model, clip, vae = self._base_nodes()
        nodes.update({
            "11": {"class_type": "InstantIDModelLoader", "inputs": {"instantid_file": "ip-adapter.bin"}},
            "38": {"class_type": "InstantIDFaceAnalysis", "inputs": {"provider": "CPU"}},
            "16": {"class_type": "ControlNetLoader", "inputs": {"control_net_name": "instantid_controlnet.safetensors"}},
            "13": {"class_type": "LoadImage", "inputs": {"image": ref_name}},
            "6": {"class_type": "CLIPTextEncode", "inputs": {"text": prompt, "clip": clip}},
            "7": {"class_type": "CLIPTextEncode", "inputs": {"text": _NEGATIVE, "clip": clip}},
            "60": {"class_type": "ApplyInstantID", "inputs": {
                "instantid": ["11", 0], "insightface": ["38", 0], "control_net": ["16", 0],
                "image": ["13", 0], "model": model, "positive": ["6", 0], "negative": ["7", 0],
                "weight": self.iid_weight, "start_at": 0.0, "end_at": self.iid_end}},
            "5": {"class_type": "EmptyLatentImage", "inputs": {"width": _W, "height": _H, "batch_size": 1}},
            "3": self._sampler(seed, ["60", 0], ["60", 1], ["60", 2]),
            "8": {"class_type": "VAEDecode", "inputs": {"samples": ["3", 0], "vae": vae}},
            "9": {"class_type": "SaveImage", "inputs": {"images": ["8", 0], "filename_prefix": "pf"}},
        })
        return nodes

    # ─── Interfaz ImageProvider ───
    def generate(self, prompt: str, out_path: Path, reference: Path | None = None,
                 style: str | None = None) -> Path:
        seed = uuid.uuid4().int % (2 ** 32)
        self._style_ov = style  # fuerza un estilo (Skybot) o None = el de la UI
        # El ESTILO va al PRINCIPIO (SDXL pondera más los primeros tokens).
        full = f"{_style_suffix(style)}, {prompt.strip()}, {_QUALITY}"
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
