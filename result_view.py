import logging
import discord
import discord.ui
from typing import Optional, List
from sd_client import SDClient, SDProcessResult, SDProcessArguments
from utils import images_to_attachments, make_comment_from_interaction, ActionButton, select_best_tensor_size
from repaint_modal import RepaintModal


RESULT_TXT2IMG = 0
RESULT_IMG2IMG = 1


class ResultView(discord.ui.View):
    def __init__(self, robot, parent_msg, result_type: int, args: SDProcessArguments, result: SDProcessResult,
                 current_content: str, current_attachments: List[discord.File]):
        super(ResultView, self).__init__(timeout=3600)
        self._robot = robot
        self._parent_msg = parent_msg  # type: discord.Message
        self._result_type = result_type
        self._args: SDProcessArguments = args.clone()
        self._result = result
        self._current_content = current_content
        self._current_attachments = current_attachments

        self._upscale_result = None

        # UI 控件
        self._btn_again = ActionButton(style=discord.ButtonStyle.green, label="再次施法")
        self._btn_again.set_callback(self._on_again_clicked)
        self.add_item(self._btn_again)

        self._btn_repaint = ActionButton(style=discord.ButtonStyle.blurple, label="施加变幻")
        self._btn_repaint.set_callback(self._on_repaint_clicked)
        self.add_item(self._btn_repaint)

        self._btn_upscale_x2 = ActionButton(style=discord.ButtonStyle.blurple, label="x2")
        self._btn_upscale_x2.set_callback(lambda i: self._on_upscale_clicked(i, 2))
        self.add_item(self._btn_upscale_x2)

        self._btn_upscale_x3 = ActionButton(style=discord.ButtonStyle.blurple, label="x3")
        self._btn_upscale_x3.set_callback(lambda i: self._on_upscale_clicked(i, 3))
        self.add_item(self._btn_upscale_x3)

    async def _refresh_parent_msg(self):
        # attachment 要重置
        if self._current_attachments is not None:
            for e in self._current_attachments:
                e.reset()
        await self._parent_msg.edit(content=self._current_content, attachments=self._current_attachments, view=self)

    async def _on_again_clicked(self, interaction: discord.Interaction):
        await interaction.response.defer()

        # 在频道发送一条新消息
        msg = await interaction.channel.send(content="施法准备中", reference=self._parent_msg)

        if self._result_type == RESULT_TXT2IMG:
            # 交由 process_paint_command 处理
            args = self._args.clone()
            args.seed = None  # 此时 Seed 总是 None
            args.comment = make_comment_from_interaction(interaction)
            await self._robot.process_paint_command(msg, args)
        else:
            assert self._result_type == RESULT_IMG2IMG
            # 交由 process_repaint_command 处理
            args = self._args.clone()
            args.seed = None  # 此时 Seed 总是 None
            args.comment = make_comment_from_interaction(interaction)
            await self._robot.process_repaint_command(msg, args)

    async def _on_repaint_clicked(self, interaction: discord.Interaction):
        # 发送模态消息
        args = self._args.clone()
        if self._upscale_result is not None:  # 在有 upscale 的情况下，选用 upscale 的结果
            args.width, args.height = select_best_tensor_size(self._upscale_result.width, self._upscale_result.height)
            args.images = self._upscale_result.images
        else:
            args.width, args.height = select_best_tensor_size(self._result.width, self._result.height)
            args.images = [self._result.images[0]]  # 我们总是取第一张图
        args.comment = make_comment_from_interaction(interaction)
        await interaction.response.send_modal(RepaintModal(self._robot, args))

    async def _on_upscale_clicked(self, interaction: discord.Interaction, scale: int):
        await interaction.response.defer()

        # 禁用按钮并刷新 UI
        self._btn_upscale_x2.disabled = True
        self._btn_upscale_x3.disabled = True
        if scale == 2:
            self._btn_upscale_x2.label = "处理中"
        else:
            assert scale == 3
            self._btn_upscale_x3.label = "处理中"
        await self._refresh_parent_msg()

        # 发起上采样操作
        sd_client = self._robot.get_sd_client()  # type: SDClient
        try:
            # 我们总是取第一张图
            self._upscale_result = await sd_client.upscale(self._result.images[0], scale,
                                                           make_comment_from_interaction(interaction))
        except Exception:
            logging.exception("Processing error")
            # 恢复按钮
            self._btn_upscale_x2.disabled = False
            self._btn_upscale_x3.disabled = False
            if scale == 2:
                self._btn_upscale_x2.label = "x2"
            else:
                self._btn_upscale_x3.label = "x3"
            await self._refresh_parent_msg()
            return

        # 刷新 Attachment
        attachments = images_to_attachments(self._upscale_result.images)

        # 恢复按钮
        self._btn_upscale_x2.disabled = False
        self._btn_upscale_x3.disabled = False

        # 消除按钮
        self.remove_item(self._btn_upscale_x2)  # 放大 3 倍的时候可以连 2 倍按钮一起消除
        if scale == 3:
            self.remove_item(self._btn_upscale_x3)

        # 刷新消息
        self._current_attachments = attachments
        await self._refresh_parent_msg()
