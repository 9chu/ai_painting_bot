import pydantic
from typing import List


class Config(pydantic.BaseModel):
    bot_token: str
    sd_api_base_url: str
    sd_api_prefix: str = '/api'
    sd_api_secret: str
    default_negative_prompts: str = 'lowres, bad anatomy, bad hands, text, error, missing fingers, extra digit, ' \
                                    'fewer digits, cropped, worst quality, low quality, normal quality, ' \
                                    'jpeg artifacts, signature, watermark, username, blurry'
    available_modules: List[str] = []
