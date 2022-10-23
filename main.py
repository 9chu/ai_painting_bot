#!python3
# -*- coding: utf-8 -*-
import asyncio
import logging
import argparse
from config import Config
from robot import Robot


def main():
    parser = argparse.ArgumentParser(description="Discord AI painting robot")
    parser.add_argument("--config", dest="config", required=True, type=str, help="Configure file path")
    parser.add_argument("--verbose", dest="verbose", required=False, action="store_true", default=False,
                        help="Show debug logs")
    args = parser.parse_args()

    # 初始化日志
    logger = logging.getLogger()
    logger.setLevel(logging.DEBUG)
    logger_format = logging.Formatter("[%(asctime)s][%(levelname)s][%(module)s:%(funcName)s:%(lineno)d] %(message)s")
    logger_output = logging.StreamHandler()
    logger_output.setLevel(logging.DEBUG if args.verbose else logging.INFO)
    logger_output.setFormatter(logger_format)
    logger.addHandler(logger_output)

    # 加载配置文件
    cfg = Config.parse_file(args.config)

    # 创建机器人
    robot = Robot(cfg)

    loop = asyncio.get_event_loop()
    loop.run_until_complete(robot.run())


if __name__ == "__main__":
    main()
