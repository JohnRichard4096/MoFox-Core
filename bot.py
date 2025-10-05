# import asyncio
import asyncio
import os
import platform
import sys
import time
import traceback
from pathlib import Path

from colorama import Fore, init
from dotenv import load_dotenv  # 处理.env文件
from rich.traceback import install

# maim_message imports for console input
# 最早期初始化日志系统，确保所有后续模块都使用正确的日志格式
from src.common.logger import get_logger, initialize_logging, shutdown_logging

# UI日志适配器
initialize_logging()

from src.main import MainSystem  # noqa
from src import BaseMain
from src.manager.async_task_manager import async_task_manager
from src.chat.knowledge.knowledge_lib import initialize_lpmm_knowledge
from src.config.config import global_config
from src.common.database.database import initialize_sql_database
from src.common.database.sqlalchemy_models import initialize_database as init_db

logger = get_logger("main")

install(extra_lines=3)

# 设置工作目录为脚本所在目录
script_dir = os.path.dirname(os.path.abspath(__file__))
os.chdir(script_dir)
logger.info(f"已设置工作目录为: {script_dir}")


# 检查并创建.env文件
def ensure_env_file():
    """确保.env文件存在，如果不存在则从模板创建"""
    env_file = Path(".env")
    template_env = Path("template/template.env")

    if not env_file.exists():
        if template_env.exists():
            logger.info("未找到.env文件，正在从模板创建...")
            import shutil

            shutil.copy(template_env, env_file)
            logger.info("已从template/template.env创建.env文件")
            logger.warning("请编辑.env文件，将EULA_CONFIRMED设置为true并配置其他必要参数")
        else:
            logger.error("未找到.env文件和template.env模板文件")
            sys.exit(1)


# 确保环境文件存在
ensure_env_file()

# 加载环境变量
load_dotenv()

confirm_logger = get_logger("confirm")
# 获取没有加载env时的环境变量

uvicorn_server = None
driver = None
app = None
loop = None
main_system = None


async def request_shutdown() -> bool:
    """请求关闭程序"""
    try:
        if loop and not loop.is_closed():
            try:
                loop.run_until_complete(graceful_shutdown(maibot.main_system))
            except Exception as ge:  # 捕捉优雅关闭时可能发生的错误
                logger.error(f"优雅关闭时发生错误: {ge}")
                return False
        return True
    except Exception as e:
        logger.error(f"请求关闭程序时发生错误: {e}")
        return False


def easter_egg():
    # 彩蛋
    init()
    text = "多年以后，面对AI行刑队，张三将会回想起他2023年在会议上讨论人工智能的那个下午"
    rainbow_colors = [Fore.RED, Fore.YELLOW, Fore.GREEN, Fore.CYAN, Fore.BLUE, Fore.MAGENTA]
    rainbow_text = ""
    for i, char in enumerate(text):
        rainbow_text += rainbow_colors[i % len(rainbow_colors)] + char
    logger.info(rainbow_text)


async def graceful_shutdown(main_system_instance):
    """优雅地关闭所有系统组件"""
    try:
        logger.info("正在优雅关闭麦麦...")

        # 停止MainSystem中的组件，它会处理服务器等
        if main_system_instance and hasattr(main_system_instance, "shutdown"):
            logger.info("正在关闭MainSystem...")
            await main_system_instance.shutdown()

        # 停止聊天管理器
        try:
            from src.chat.message_receive.chat_stream import get_chat_manager
            chat_manager = get_chat_manager()
            if hasattr(chat_manager, "stop_auto_save"):
                logger.info("正在停止聊天管理器...")
                chat_manager.stop_auto_save()
        except Exception as e:
            logger.warning(f"停止聊天管理器时出错: {e}")

        # 停止情绪管理器
        try:
            from src.mood.mood_manager import mood_manager
            if hasattr(mood_manager, "stop"):
                logger.info("正在停止情绪管理器...")
                await mood_manager.stop()
        except Exception as e:
            logger.warning(f"停止情绪管理器时出错: {e}")

        # 停止记忆系统
        try:
            from src.chat.memory_system.memory_manager import memory_manager
            if hasattr(memory_manager, "shutdown"):
                logger.info("正在停止记忆系统...")
                await memory_manager.shutdown()
        except Exception as e:
            logger.warning(f"停止记忆系统时出错: {e}")


        # 停止所有异步任务
        try:
            await async_task_manager.stop_and_wait_all_tasks()
        except Exception as e:
            logger.warning(f"停止异步任务管理器时出错: {e}")

        # 获取所有剩余任务，排除当前任务
        remaining_tasks = [t for t in asyncio.all_tasks() if t is not asyncio.current_task()]

        if remaining_tasks:
            logger.info(f"正在取消 {len(remaining_tasks)} 个剩余任务...")

            # 取消所有剩余任务
            for task in remaining_tasks:
                if not task.done():
                    task.cancel()

            # 等待所有任务完成，设置超时
            try:
                await asyncio.wait_for(asyncio.gather(*remaining_tasks, return_exceptions=True), timeout=15.0)
                logger.info("所有剩余任务已成功取消")
            except asyncio.TimeoutError:
                logger.warning("等待任务取消超时，强制继续关闭")
            except Exception as e:
                logger.error(f"等待任务取消时发生异常: {e}")

        logger.info("麦麦优雅关闭完成")

        # 关闭日志系统，释放文件句柄
        shutdown_logging()

        # 尝试停止事件循环
        try:
            loop = asyncio.get_running_loop()
            if loop.is_running():
                loop.stop()
                logger.info("事件循环已请求停止")
        except RuntimeError:
            pass  # 没有正在运行的事件循环

    except Exception as e:
        logger.error(f"麦麦关闭失败: {e}", exc_info=True)


def check_eula():
    """检查EULA和隐私条款确认状态 - 环境变量版（类似Minecraft）"""
    # 检查环境变量中的EULA确认
    eula_confirmed = os.getenv("EULA_CONFIRMED", "").lower()

    if eula_confirmed == "true":
        logger.info("EULA已通过环境变量确认")
        return

    # 如果没有确认，提示用户
    confirm_logger.critical("您需要同意EULA和隐私条款才能使用MoFox_Bot")
    confirm_logger.critical("请阅读以下文件：")
    confirm_logger.critical("  - EULA.md (用户许可协议)")
    confirm_logger.critical("  - PRIVACY.md (隐私条款)")
    confirm_logger.critical("然后编辑 .env 文件，将 'EULA_CONFIRMED=false' 改为 'EULA_CONFIRMED=true'")

    # 等待用户确认
    while True:
        try:
            load_dotenv(override=True)  # 重新加载.env文件

            eula_confirmed = os.getenv("EULA_CONFIRMED", "").lower()
            if eula_confirmed == "true":
                confirm_logger.info("EULA确认成功，感谢您的同意")
                return

            confirm_logger.critical("请修改 .env 文件中的 EULA_CONFIRMED=true 后重新启动程序")
            input("按Enter键检查.env文件状态...")

        except KeyboardInterrupt:
            confirm_logger.info("用户取消，程序退出")
            sys.exit(0)
        except Exception as e:
            confirm_logger.error(f"检查EULA状态失败: {e}")
            sys.exit(1)


class MaiBotMain(BaseMain):
    """麦麦机器人主程序类"""

    def __init__(self):
        super().__init__()
        self.main_system = None

    def setup_timezone(self):
        """设置时区"""
        if platform.system().lower() != "windows":
            time.tzset()  # type: ignore

    def check_and_confirm_eula(self):
        """检查并确认EULA和隐私条款"""
        check_eula()
        logger.info("检查EULA和隐私条款完成")

    async def initialize_database(self):
        """初始化数据库"""

        logger.info("正在初始化数据库连接...")
        try:
            await initialize_sql_database(global_config.database)
            logger.info(f"数据库连接初始化成功，使用 {global_config.database.database_type} 数据库")
        except Exception as e:
            logger.error(f"数据库连接初始化失败: {e}")
            raise e

    async def initialize_database_async(self):
        """异步初始化数据库表结构"""
        logger.info("正在初始化数据库表结构...")
        try:
            await init_db()
            logger.info("数据库表结构初始化完成")
        except Exception as e:
            logger.error(f"数据库表结构初始化失败: {e}")
            raise e

    def create_main_system(self):
        """创建MainSystem实例"""
        self.main_system = MainSystem()
        return self.main_system

    async def run(self):
        """运行主程序"""
        self.setup_timezone()
        self.check_and_confirm_eula()
        await self.initialize_database()

        return self.create_main_system()


if __name__ == "__main__":
    exit_code = 0  # 用于记录程序最终的退出状态
    try:
        # 创建MaiBotMain实例并获取MainSystem
        maibot = MaiBotMain()

        # 创建事件循环
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

        try:
            # 异步初始化数据库和表结构
            main_system = loop.run_until_complete(maibot.run())
            loop.run_until_complete(maibot.initialize_database_async())
            # 执行初始化和任务调度
            loop.run_until_complete(main_system.initialize())
            initialize_lpmm_knowledge()
            # Schedule tasks returns a future that runs forever.
            # We can run console_input_loop concurrently.
            main_tasks = loop.create_task(main_system.schedule_tasks())
            loop.run_until_complete(main_tasks)

        except KeyboardInterrupt:
            logger.warning("收到中断信号，正在优雅关闭...")
            # The actual shutdown logic is now in the finally block.

    except Exception as e:
        logger.error(f"主程序发生异常: {e!s} {traceback.format_exc()!s}")
        exit_code = 1  # 标记发生错误
    finally:
        # 确保 loop 在任何情况下都尝试关闭（如果存在且未关闭）
        if "loop" in locals() and loop and not loop.is_closed():
            logger.info("开始执行最终关闭流程...")
            try:
                # 传递main_system实例
                loop.run_until_complete(graceful_shutdown(maibot.main_system))
            except Exception as ge:
                logger.error(f"优雅关闭时发生错误: {ge}")
            loop.close()
            logger.info("事件循环已关闭")

        # 在程序退出前暂停，让你有机会看到输出
        # input("按 Enter 键退出...")  # <--- 添加这行
        sys.exit(exit_code)  # <--- 使用记录的退出码
