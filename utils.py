import io
import re
import json
import discord.ui
from typing import List, Optional


def images_to_attachments(images: List[bytes]) -> List[discord.File]:
    attachments = []
    for i in range(0, len(images)):
        img = images[i]
        arr = io.BytesIO()
        arr.write(img)
        arr.seek(0)
        file = discord.File(fp=arr, filename=f"{i + 1}.png")
        attachments.append(file)
    return attachments


def get_best_tensor_size(direction: str):
    # 在 7.5G 显存下（Tesla P4）可以使用的最大大小
    width, height = 704, 704
    if direction == "portrait" or direction == "纵向":
        width, height = 576, 960
    elif direction == "landscape" or direction == "横向":
        width, height = 960, 576
    return width, height


def select_best_tensor_size(width: int, height: int):
    # 在 7.5G 显存下（Tesla P4）可以使用的最大块数目
    max_blocks = 135
    max_pixels = max_blocks * 64 * 64

    # 提升质量，不低于 512x512
    min_blocks = 64
    min_pixels = min_blocks * 64 * 64

    total_pixels = width * height
    if total_pixels < min_pixels:
        scale = min_pixels / total_pixels
        width *= scale
        height *= scale

    total_pixels = width * height
    if total_pixels > max_pixels:
        scale = max_pixels / total_pixels
        width *= scale
        height *= scale

    w_blocks = max(1, width // 64)
    h_blocks = max(1, height // 64)
    assert w_blocks * h_blocks <= max_blocks
    return w_blocks * 64, h_blocks * 64


def mix_negative_prompts(input_negative: Optional[str], default_negative_prompts: str):
    if not input_negative:
        return default_negative_prompts
    return input_negative.replace("$", default_negative_prompts)


def make_comment_from_interaction(interaction: discord.Interaction):
    return json.dumps({
        "from": "discord",
        "name": interaction.user.name,
        "id": interaction.user.id,
        "ch_id": interaction.channel_id,
    })


def make_comment_from_message(message: discord.Message):
    return json.dumps({
        "from": "discord",
        "name": message.author.name,
        "id": message.author.id,
        "ch_id": message.channel.id,
    })


# discord.py 似乎没有提供接受回调的类，需要自己覆盖 calllback 方法？
class ActionButton(discord.ui.Button):
    def __init__(self, **kwargs):
        super(ActionButton, self).__init__(**kwargs)
        self._callback = None

    def set_callback(self, cb):
        self._callback = cb

    async def callback(self, interaction: discord.Interaction):
        if self._callback is not None:
            await self._callback(interaction)
