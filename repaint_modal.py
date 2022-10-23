import logging
import discord
import discord.ui
from sd_client import SDProcessArguments


def _make_additional_arguments(args: SDProcessArguments):
    args_list = [f"steps: {args.steps}"]
    if args.seed is not None:
        args_list.append(f"seed: {args.seed}")
    if args.module is not None:
        args_list.append(f"module: {args.module}")
    return " ".join(args_list)


def _extract_additional_arguments(target: SDProcessArguments, args: str):
    t = SDProcessArguments()
    t.from_common_args(args)
    target.seed = t.seed
    target.steps = t.steps
    target.module = t.module


class RepaintModal(discord.ui.Modal):
    def __init__(self, robot, args: SDProcessArguments):
        super(RepaintModal, self).__init__(title="变幻魔法", timeout=3600)
        self._robot = robot
        self._args: SDProcessArguments = args.clone()

        # 准备 UI
        self._input_prompts = discord.ui.TextInput(label="Prompts", default=self._args.prompts)
        self.add_item(self._input_prompts)

        self._input_negative = discord.ui.TextInput(label="Negative", default=self._args.negative_prompts)
        self.add_item(self._input_negative)

        self._input_scale = discord.ui.TextInput(label="CFG Scale", default=str(self._args.scale))
        self.add_item(self._input_scale)

        self._input_denoise = discord.ui.TextInput(label="Denoise", default=str(self._args.denoise))
        self.add_item(self._input_denoise)

        self._input_additional = discord.ui.TextInput(label="Additional Arguments", required=False,
                                                      default=_make_additional_arguments(self._args))
        self.add_item(self._input_additional)

    async def on_submit(self, interaction: discord.Interaction):
        # 参数赋值和检查
        prompts = str(self._input_prompts).strip()
        negative = str(self._input_negative).strip()
        scale = str(self._input_scale).strip()
        denoise = str(self._input_denoise).strip()
        additional = str(self._input_additional).strip()
        try:
            self._args.prompts = prompts
            self._args.negative_prompts = negative
            self._args.scale = float(scale)
            self._args.denoise = float(denoise)
            if len(self._args.prompts) == 0:
                raise RuntimeError("Prompts is empty")
            _extract_additional_arguments(self._args, additional)
            self._args.limit_args_range()
        except Exception:
            logging.exception("Argument check failed")
            await interaction.response.send_message(content="非法的咒语")
            return

        # 发起操作
        await interaction.response.defer()
        wb_msg = await interaction.followup.send(content="施法准备中")
        await self._robot.process_repaint_command(wb_msg, self._args, True)
