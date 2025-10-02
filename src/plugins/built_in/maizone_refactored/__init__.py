"""
让框架能够发现并加载子目录中的组件。
"""

from .actions.read_feed_action import ReadFeedAction as ReadFeedAction
from .actions.send_feed_action import SendFeedAction as SendFeedAction
from .commands.send_feed_command import SendFeedCommand as SendFeedCommand
from .plugin import MaiZoneRefactoredPlugin as MaiZoneRefactoredPlugin
