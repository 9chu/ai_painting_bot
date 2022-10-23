import re
import zlib
import json
import math
import asyncio
import base64
import logging
import aiohttp
import aiohttp.client_exceptions
from typing import Optional, List
from config import Config


_COMMON_ARG_REGEX = re.compile(r"\s*(prompts|negative|resize|seed|scale|module|steps|denoise)\s*:\s*((.(?!prompts\s*:"
                               r"|negative\s*:|resize\s*:|seed\s*:|scale\s*:|module\s*:|steps\s*:|denoise\s*:))+)",
                               re.IGNORECASE)


def b64_to_bytes(b64: List[str]) -> List[bytes]:
    return [base64.b64decode(x) for x in b64]


def bytes_to_b64(b: List[bytes]) -> List[str]:
    return [base64.b64encode(x).decode('ascii') for x in b]


def _clamp_with_default(v: Optional[float], d: float, mi: float, ma: float):
    if v is None:
        v = d
    if v < mi:
        v = mi
    if v > ma:
        v = ma
    return v


class SDProcessArguments:
    def __init__(self):
        self.width = 512
        self.height = 512
        self.prompts = ""
        self.negative_prompts = ""
        self.count = 1
        self.steps = 30
        self.scale = 12
        self.denoise = 0.7
        self.images: Optional[List[bytes]] = None
        self.resize_mode = 2
        self.seed: Optional[int] = None
        self.module: Optional[str] = None
        self.comment: Optional[str] = None

    def from_common_args(self, args: str):
        raw_args = {}

        pos = 0
        m = re.match(_COMMON_ARG_REGEX, args[pos:])
        while m:
            k = m.group(1)
            v = m.group(2).strip()
            raw_args[k] = v
            pos = pos + m.end()
            if pos >= len(args):
                break
            m = re.match(_COMMON_ARG_REGEX, args[pos:])

        if pos < len(args):
            raise RuntimeError(f"Not all input are parsed")

        self.prompts = raw_args.get("prompts", "")
        self.negative_prompts = raw_args.get("negative", "")
        self.steps = int(raw_args.get("steps", "30"))
        self.scale = float(raw_args.get("scale", "12"))
        self.denoise = float(raw_args.get("denoise", "0.7"))
        self.resize_mode = int(raw_args.get("resize", "2"))
        self.seed = int(raw_args["seed"]) if "seed" in raw_args else None
        self.module = raw_args.get("module", None)
        self.limit_args_range()

    def limit_args_range(self):
        self.steps = math.floor(_clamp_with_default(self.steps, 30, 1, 50))
        self.scale = _clamp_with_default(self.scale, 12, 1, 30)
        self.denoise = _clamp_with_default(self.denoise, 0.7, 0.1, 1)
        self.resize_mode = math.floor(_clamp_with_default(self.resize_mode, 2, 0, 2))

    def clone(self):
        ret = SDProcessArguments()
        ret.width = self.width
        ret.height = self.height
        ret.prompts = self.prompts
        ret.negative_prompts = self.negative_prompts
        ret.count = self.count
        ret.steps = self.steps
        ret.scale = self.scale
        ret.denoise = self.denoise
        ret.images = self.images
        ret.resize_mode = self.resize_mode
        ret.seed = self.seed
        ret.module = self.module
        ret.comment = self.comment
        return ret


class SDProcessResult:
    def __init__(self, task_id: int, width: int, height: int, images: List[bytes], seed: Optional[int] = None):
        self.task_id = task_id
        self.width = width
        self.height = height
        self.images = images
        self.seed = seed


class SDClient:
    def __init__(self, config: Config):
        self._config = config
        self._session = aiohttp.ClientSession(self._config.sd_api_base_url,
                                              headers={"X-API-SECRET": self._config.sd_api_secret})

    async def _call(self, service: str, method: str, payload, timeout=300):
        data = json.dumps(payload).encode('utf-8')
        headers = {"Content-Type": "application/json"}
        if len(data) > 4096:
            data = zlib.compress(data)
            headers["Content-Encoding"] = "deflate"

        async with self._session.post(f"{self._config.sd_api_prefix}/{service}/{method}", data=data, headers=headers,
                                      timeout=timeout) as resp:
            r = await resp.json()
            if r["code"] != 0:
                raise RuntimeError(f"API Error: {r['msg']} ({r['code']})")
            return r["data"]

    async def _check_task(self, task_id: int, on_progress=None):
        retry = 0
        last_status = -1
        while True:
            try:
                state = await self._call("Task", "getTaskState", {"taskId": task_id}, timeout=180)
            except (aiohttp.client_exceptions.ClientConnectionError,
                    aiohttp.client_exceptions.ClientPayloadError,
                    asyncio.TimeoutError) as ex:
                # 网络问题多次尝试
                logging.exception("Network error")
                retry += 1
                if retry > 5:
                    raise ex
                await asyncio.sleep(1)
                continue

            status = state["status"]
            if status != last_status:
                retry = 0
                last_status = status

            if status == 0:  # pending
                await asyncio.sleep(5)
            elif status == 1:  # running
                if state["progress"] is not None and on_progress is not None:
                    await on_progress(state["progress"])
                await asyncio.sleep(2)
            if status == 2:  # finished
                return state
            elif status == 3:  # error
                raise RuntimeError(f"Task Error: {state['errMsg']}")

    async def img2img(self, args: SDProcessArguments, on_progress=None):
        payload = {
            "width": args.width,
            "height": args.height,
            "prompts": args.prompts,
            "negativePrompts": args.negative_prompts,
            "count": args.count,
            "steps": args.steps,
            "scale": args.scale,
            "seed": args.seed,
            "module": args.module,
            "comment": args.comment,
            "denoise": args.denoise,
            "resizeMode": args.resize_mode,
            "initialImages": bytes_to_b64(args.images),
        }
        task_id = await self._call("Task", "submitImg2ImgTask", payload)
        ret = await self._check_task(task_id, on_progress)
        return SDProcessResult(task_id, ret["resultWidth"], ret["resultHeight"], b64_to_bytes(ret["resultImages"]),
                               ret["resultSeed"])

    async def txt2img(self, args: SDProcessArguments, on_progress=None):
        payload = {
            "width": args.width,
            "height": args.height,
            "prompts": args.prompts,
            "negativePrompts": args.negative_prompts,
            "count": args.count,
            "steps": args.steps,
            "scale": args.scale,
            "seed": args.seed,
            "module": args.module,
            "comment": args.comment,
        }
        task_id = await self._call("Task", "submitTxt2ImgTask", payload)
        ret = await self._check_task(task_id, on_progress)
        return SDProcessResult(task_id, ret["resultWidth"], ret["resultHeight"], b64_to_bytes(ret["resultImages"]),
                               ret["resultSeed"])

    async def upscale(self, image: bytes, scale: float, comment: Optional[str]):
        assert 1 < scale <= 4

        payload = {
            "image": base64.b64encode(image).decode('utf-8'),
            "scale": scale,
            "comment": comment,
        }
        task_id = await self._call("Task", "submitUpscaleTask", payload)
        ret = await self._check_task(task_id, None)
        return SDProcessResult(task_id, ret["resultWidth"], ret["resultHeight"], b64_to_bytes(ret["resultImages"]))
