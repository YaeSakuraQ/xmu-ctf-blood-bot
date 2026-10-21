"""NoneBot2 entrypoint.

Run with ``python bot.py`` (or the Docker image's default CMD).
"""

import nonebot
from nonebot.adapters.onebot.v11 import Adapter as OneBotV11Adapter

nonebot.init()
nonebot.init(apscheduler_autostart=True)
nonebot.init(apscheduler_config={"apscheduler.timezone": "Asia/Shanghai"})

driver = nonebot.get_driver()
driver.register_adapter(OneBotV11Adapter)

nonebot.load_plugin("nonebot_plugin_apscheduler")
nonebot.load_plugin("plugins.ctf_blood")

if __name__ == "__main__":
    nonebot.run()
