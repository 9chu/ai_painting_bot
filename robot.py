import io
import os
import logging
import discord
from typing import List, Optional
from PIL import Image
from config import Config
from sd_client import SDClient, SDProcessArguments
from result_view import ResultView, RESULT_TXT2IMG, RESULT_IMG2IMG
from repaint_view import OpenRepaintModalView
from utils import images_to_attachments, mix_negative_prompts, get_best_tensor_size, select_best_tensor_size, \
    make_comment_from_interaction, make_comment_from_message


class Robot:
    def __init__(self, config: Config):
        self._config = config

        # 建立客户端
        self._client = discord.Client(intents=discord.Intents(messages=True, dm_messages=True),
                                      proxy=os.getenv("https_proxy", None))

        @self._client.event
        async def on_ready():
            await self._on_ready()

        @self._client.event
        async def on_message(message):
            await self._on_message(message)

        # 建立命令树
        self._command_tree = discord.app_commands.CommandTree(self._client)

        # /paint
        @self._command_tree.command(name="paint", description="发动召唤魔法")
        async def paint(interaction: discord.Interaction, prompts: str, size: Optional[str] = None,
                        negative: Optional[str] = None, scale: Optional[float] = None, seed: Optional[int] = None,
                        module: Optional[str] = None, steps: Optional[int] = None):
            if size is None:
                size = "portrait"

            # 设置参数
            args = SDProcessArguments()
            args.width, args.height = get_best_tensor_size(size)
            args.prompts = prompts
            args.negative_prompts = "$" if negative is None else negative  # 使用默认值替换
            args.module = module
            args.comment = make_comment_from_interaction(interaction)
            if steps is not None:
                args.steps = steps
            if scale is not None:
                args.scale = scale
            if seed is not None and seed >= 0:
                args.seed = seed
            args.limit_args_range()

            # 通知稍后处理
            await interaction.response.defer()
            wb_msg = await interaction.followup.send(content="施法准备中")  # type: discord.WebhookMessage

            # 发起后继请求
            await self.process_paint_command(wb_msg, args)

        @paint.autocomplete("size")
        async def paint_size_autocomplete(interaction: discord.Interaction, current: str) \
                -> List[discord.app_commands.Choice[str]]:
            return [
                discord.app_commands.Choice(name="纵向", value="portrait"),
                discord.app_commands.Choice(name="横向", value="landscape"),
                discord.app_commands.Choice(name="方形", value="square")
            ]

        @paint.autocomplete("module")
        async def paint_module_autocomplete(interaction: discord.Interaction, current: str) \
                -> List[discord.app_commands.Choice[str]]:
            return [discord.app_commands.Choice(name=v, value=v)
                    for v in self._config.available_modules if v.find(current) >= 0]

        # SD 客户端
        self._sd_client = SDClient(config)

    async def _on_ready(self):
        logging.info("Prepare to sync commands")
        await self._command_tree.sync()
        logging.info("Ready to GO!")

    async def _on_message(self, message: discord.Message):
        if message.author == self._client.user:  # 跳过自己发的
            return
        if message.mention_everyone:  # 跳过发给所有人的
            return

        clean_message = message.clean_content.strip()  # type: str
        if message.channel.type != discord.ChannelType.private:  # 群消息保证提及自己才会触发
            if len(message.mentions) != 1:
                return

            # 干掉消息前缀或后缀
            prefix_or_postfix = f'@{self._client.user.name}'
            if clean_message.startswith(prefix_or_postfix):
                clean_message = clean_message[len(prefix_or_postfix):].strip()
            elif clean_message.endswith(prefix_or_postfix):
                clean_message = clean_message[0: -len(prefix_or_postfix)]
            else:
                # at 位于中间的不予处理
                return

        # AppCommand 不能支持增加附件，因此我们通过 at 机器人的方式完成 img2img 初始图片的捕获
        if clean_message.startswith("/repaint"):
            await self._on_repaint_message(message, clean_message[len("/repaint"):])

    async def _on_repaint_message(self, message: discord.Message, clean_message: str):
        if len(message.attachments) == 0:
            await message.channel.send(content="需要施法材料", reference=message)
            return

        # 创建参数
        args = SDProcessArguments()
        args.comment = make_comment_from_message(message)
        try:
            args.from_common_args(clean_message)
            if len(args.negative_prompts) == 0:
                args.negative_prompts = self._config.default_negative_prompts
        except Exception:
            await message.channel.send(content="需要提供正确的咒语", reference=message)
            return

        # module 校验
        if args.module is not None and args.module not in self._config.available_modules:
            await message.channel.send(content="不支持的模组", reference=message)
            return

        # 读取附件
        image = await message.attachments[0].read(use_cached=True)  # 我们总是取第一张图
        args.images = [image]

        # 决定图片采用的方向/大小
        try:
            with io.BytesIO() as fp:
                fp.write(image)
                fp.seek(0, io.SEEK_SET)
                img = Image.open(fp)
                args.width, args.height = select_best_tensor_size(img.size[0], img.size[1])
        except Exception:
            logging.exception("Processing error")
            await message.channel.send(content="无效的施法材料", reference=message)
            return

        # 如果没有提供 prompts，弹出 UI
        if len(args.prompts) == 0:
            view = OpenRepaintModalView(self, args)
            await message.channel.send(content="施法需要足够的魔素", view=view, reference=message)
        else:
            wb_msg = await message.channel.send(content="施法准备中", reference=message)
            await self.process_repaint_command(wb_msg, args, False)

    def get_sd_client(self):
        return self._sd_client

    async def run(self):
        await self._client.start(self._config.bot_token)

    async def process_paint_command(self, base_msg: discord.Message, args: SDProcessArguments):
        # 统一处理负面关键词
        args.negative_prompts = mix_negative_prompts(args.negative_prompts, self._config.default_negative_prompts)

        # 发起操作
        try:
            async def on_progress_callback(progress):
                await base_msg.edit(content="吟唱：%.2f %%" % (progress * 100))

            result = await self._sd_client.txt2img(args, on_progress=on_progress_callback)
        except Exception as ex:
            logging.exception("Processing error")
            await base_msg.edit(content=f"{ex}")
            return

        # 完成，转换到文件
        attachments = images_to_attachments(result.images)

        # 消息部分
        content = f"DDIM，种子：{result.seed}，步长：{args.steps}，CFG Scale：{args.scale}"
        if args.module is not None:
            content += f"，模组：{args.module}"

        # 控制视图
        view = ResultView(self, base_msg, RESULT_TXT2IMG, args, result, content, attachments)

        # 回复
        await base_msg.edit(content=content, attachments=attachments, view=view)

    async def process_repaint_command(self, base_msg: discord.Message, args: SDProcessArguments, show_prompts=False):
        # 统一处理负面关键词
        args.negative_prompts = mix_negative_prompts(args.negative_prompts, self._config.default_negative_prompts)

        # 发起操作
        try:
            async def on_progress_callback(progress):
                await base_msg.edit(content="吟唱：%.2f %%" % (progress * 100))

            result = await self._sd_client.img2img(args, on_progress=on_progress_callback)
        except Exception as ex:
            logging.exception("Processing error")
            await base_msg.edit(content=f"{ex}")
            return

        # 完成，转换到文件
        attachments = images_to_attachments(result.images)

        # 消息部分
        content_lines = []
        if show_prompts:
            content_lines.append("```")
            content_lines.append(f"Prompts: {args.prompts}")
            if args.negative_prompts != self._config.default_negative_prompts:
                content_lines.append(f"Negative prompts: {args.negative_prompts}")
            content_lines.append("```")
        content_lines.append(f"DDIM，种子：{result.seed}，步长：{args.steps}，CFG Scale：{args.scale}，"
                             f"Denoise：{args.denoise}")
        if args.module is not None:
            content_lines[len(content_lines) - 1] += f"，模组：{args.module}"
        content = "\n".join(content_lines)

        # 控制视图
        view = ResultView(self, base_msg, RESULT_IMG2IMG, args, result, content, attachments)

        # 回复
        await base_msg.edit(content=content, attachments=attachments, view=view)
