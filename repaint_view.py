import discord
import discord.ui
from result_view import ActionButton
from sd_client import SDProcessArguments
from repaint_modal import RepaintModal
from utils import make_comment_from_interaction


class OpenRepaintModalView(discord.ui.View):
    def __init__(self, robot, args: SDProcessArguments):
        super(OpenRepaintModalView, self).__init__(timeout=3600)
        self._robot = robot
        self._args = args

        # UI 控件
        self._btn_open_dialog = ActionButton(style=discord.ButtonStyle.green, label="注入魔素")
        self._btn_open_dialog.set_callback(self._on_open_dialog_clicked)
        self.add_item(self._btn_open_dialog)

    async def _on_open_dialog_clicked(self, interaction: discord.Interaction):
        args = self._args.clone()
        args.comment = make_comment_from_interaction(interaction)
        m = RepaintModal(self._robot, args)
        await interaction.response.send_modal(m)
