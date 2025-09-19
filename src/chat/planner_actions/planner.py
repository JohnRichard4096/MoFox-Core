"""
主规划器入口，负责协调 PlanGenerator, PlanFilter, 和 PlanExecutor。
集成兴趣度评分系统和用户关系追踪机制，实现智能化的聊天决策。
"""

from dataclasses import asdict
from typing import Dict, List, Optional, Tuple

from src.chat.planner_actions.action_manager import ActionManager
from src.chat.planner_actions.plan_executor import PlanExecutor
from src.chat.planner_actions.plan_filter import PlanFilter
from src.chat.planner_actions.plan_generator import PlanGenerator
from src.chat.affinity_flow.interest_scoring import InterestScoringSystem
from src.chat.affinity_flow.relationship_tracker import UserRelationshipTracker
from src.common.data_models.info_data_model import Plan
from src.common.logger import get_logger
from src.config.config import global_config
from src.plugin_system.base.component_types import ChatMode
import src.chat.planner_actions.planner_prompts #noga  # noqa: F401
# 导入提示词模块以确保其被初始化
from src.chat.planner_actions import planner_prompts  # noqa

logger = get_logger("planner")


class ActionPlanner:
    """
    增强版ActionPlanner，集成兴趣度评分和用户关系追踪机制。

    核心功能：
    1. 兴趣度评分系统：根据兴趣匹配度、关系分、提及度、时间因子对消息评分
    2. 用户关系追踪：自动追踪用户交互并更新关系分
    3. 智能回复决策：基于兴趣度阈值和连续不回复概率的智能决策
    4. 完整的规划流程：生成→筛选→执行的完整三阶段流程
    """

    def __init__(self, chat_id: str, action_manager: ActionManager):
        """
        初始化增强版ActionPlanner。

        Args:
            chat_id (str): 当前聊天的 ID。
            action_manager (ActionManager): 一个 ActionManager 实例。
        """
        self.chat_id = chat_id
        self.action_manager = action_manager
        self.generator = PlanGenerator(chat_id)
        self.filter = PlanFilter()
        self.executor = PlanExecutor(action_manager)

        # 初始化兴趣度评分系统
        self.interest_scoring = InterestScoringSystem()

        # 尝试获取全局关系追踪器，如果没有则创建新的
        try:
            from src.chat.affinity_flow.relationship_integration import get_relationship_tracker

            global_relationship_tracker = get_relationship_tracker()
            if global_relationship_tracker:
                # 使用全局关系追踪器
                self.relationship_tracker = global_relationship_tracker
                # 设置兴趣度评分系统的关系追踪器引用
                self.interest_scoring.relationship_tracker = self.relationship_tracker
                logger.info("使用全局关系追踪器")
            else:
                # 创建新的关系追踪器
                self.relationship_tracker = UserRelationshipTracker(self.interest_scoring)
                logger.info("创建新的关系追踪器实例")
        except Exception as e:
            logger.warning(f"获取全局关系追踪器失败: {e}")
            # 创建新的关系追踪器
            self.relationship_tracker = UserRelationshipTracker(self.interest_scoring)

        # 设置执行器的关系追踪器
        self.executor.set_relationship_tracker(self.relationship_tracker)

        # 规划器统计
        self.planner_stats = {
            "total_plans": 0,
            "successful_plans": 0,
            "failed_plans": 0,
            "replies_generated": 0,
            "other_actions_executed": 0,
        }

    async def plan(
        self, mode: ChatMode = ChatMode.FOCUS, message_data: dict = None
    ) -> Tuple[List[Dict], Optional[Dict]]:
        """
        执行完整的增强版规划流程。

        Args:
            mode (ChatMode): 当前的聊天模式，默认为 FOCUS。
            message_data (dict): 消息数据字典，包含：
                - unread_messages: 未读消息列表
                - history_messages: 历史消息列表（可选）

        Returns:
            Tuple[List[Dict], Optional[Dict]]: 一个元组，包含：
                - final_actions_dict (List[Dict]): 最终确定的动作列表（字典格式）。
                - final_target_message_dict (Optional[Dict]): 最终的目标消息（字典格式）。
        """
        try:
            # 提取未读消息用于兴趣度计算
            unread_messages = message_data.get("unread_messages", []) if message_data else []
            self.planner_stats["total_plans"] += 1

            return await self._enhanced_plan_flow(mode, unread_messages or [])

        except Exception as e:
            logger.error(f"规划流程出错: {e}")
            self.planner_stats["failed_plans"] += 1
            return [], None

    async def _enhanced_plan_flow(
        self, mode: ChatMode, unread_messages: List[Dict]
    ) -> Tuple[List[Dict], Optional[Dict]]:
        """执行增强版规划流程"""
        try:
            # 1. 生成初始 Plan
            initial_plan = await self.generator.generate(mode)

            # 2. 兴趣度评分 - 只对未读消息进行评分
            if unread_messages:
                bot_nickname = global_config.bot.nickname
                interest_scores = await self.interest_scoring.calculate_interest_scores(unread_messages, bot_nickname)

                # 3. 根据兴趣度调整可用动作
                if interest_scores:
                    latest_score = max(interest_scores, key=lambda s: s.total_score)
                    should_reply, score = self.interest_scoring.should_reply(latest_score)

                    reply_not_available = False
                    if not should_reply and "reply" in initial_plan.available_actions:
                        logger.info(f"消息兴趣度不足({latest_score.total_score:.2f})，移除reply动作")
                        reply_not_available = True

            base_threshold = self.interest_scoring.reply_threshold
            # 检查兴趣度是否达到阈值的0.8
            non_reply_action_interest_threshold = global_config.affinity_flow.non_reply_action_interest_threshold
            if score < non_reply_action_interest_threshold:
                logger.info(f"❌ 兴趣度不足非回复动作阈值: {score:.3f} < {non_reply_action_interest_threshold:.3f}，直接返回no_action")
                logger.info(f"📊 最低要求: {non_reply_action_interest_threshold:.3f}")
                # 直接返回 no_action
                from src.common.data_models.info_data_model import ActionPlannerInfo

                no_action = ActionPlannerInfo(
                    action_type="no_action",
                    reasoning=f"兴趣度评分 {score:.3f} 未达阈值 {non_reply_action_interest_threshold:.3f}",
                    action_data={},
                    action_message=None,
                )
                filtered_plan = initial_plan
                filtered_plan.decided_actions = [no_action]
            else:
                # 4. 筛选 Plan
                filtered_plan = await self.filter.filter(reply_not_available, initial_plan)

            # 检查filtered_plan是否有reply动作，以便记录reply action
            has_reply_action = False
            for decision in filtered_plan.decided_actions:
                if decision.action_type == "reply":
                    has_reply_action = True
            self.interest_scoring.record_reply_action(has_reply_action)

            # 5. 使用 PlanExecutor 执行 Plan
            execution_result = await self.executor.execute(filtered_plan)

            # 6. 根据执行结果更新统计信息
            self._update_stats_from_execution_result(execution_result)

            # 7. 检查关系更新
            await self.relationship_tracker.check_and_update_relationships()

            # 8. 返回结果
            return self._build_return_result(filtered_plan)

        except Exception as e:
            logger.error(f"增强版规划流程出错: {e}")
            self.planner_stats["failed_plans"] += 1
            return [], None

    def _update_stats_from_execution_result(self, execution_result: Dict[str, any]):
        """根据执行结果更新规划器统计"""
        if not execution_result:
            return

        successful_count = execution_result.get("successful_count", 0)

        # 更新成功执行计数
        self.planner_stats["successful_plans"] += successful_count

        # 统计回复动作和其他动作
        reply_count = 0
        other_count = 0

        for result in execution_result.get("results", []):
            action_type = result.get("action_type", "")
            if action_type in ["reply", "proactive_reply"]:
                reply_count += 1
            else:
                other_count += 1

        self.planner_stats["replies_generated"] += reply_count
        self.planner_stats["other_actions_executed"] += other_count

    def _build_return_result(self, plan: Plan) -> Tuple[List[Dict], Optional[Dict]]:
        """构建返回结果"""
        final_actions = plan.decided_actions or []
        final_target_message = next((act.action_message for act in final_actions if act.action_message), None)

        final_actions_dict = [asdict(act) for act in final_actions]

        if final_target_message:
            if hasattr(final_target_message, "__dataclass_fields__"):
                final_target_message_dict = asdict(final_target_message)
            else:
                final_target_message_dict = final_target_message
        else:
            final_target_message_dict = None

        return final_actions_dict, final_target_message_dict

    def get_user_relationship(self, user_id: str) -> float:
        """获取用户关系分"""
        return self.interest_scoring.get_user_relationship(user_id)

    def update_interest_keywords(self, new_keywords: Dict[str, List[str]]):
        """更新兴趣关键词（已弃用，仅保留用于兼容性）"""
        logger.info("传统关键词匹配已移除，此方法仅保留用于兼容性")
        # 此方法已弃用，因为现在完全使用embedding匹配

    def get_planner_stats(self) -> Dict[str, any]:
        """获取规划器统计"""
        return self.planner_stats.copy()

    def get_interest_scoring_stats(self) -> Dict[str, any]:
        """获取兴趣度评分统计"""
        return {
            "no_reply_count": self.interest_scoring.no_reply_count,
            "max_no_reply_count": self.interest_scoring.max_no_reply_count,
            "reply_threshold": self.interest_scoring.reply_threshold,
            "mention_threshold": self.interest_scoring.mention_threshold,
            "user_relationships": len(self.interest_scoring.user_relationships),
        }

    def get_relationship_stats(self) -> Dict[str, any]:
        """获取用户关系统计"""
        return {
            "tracking_users": len(self.relationship_tracker.tracking_users),
            "relationship_history": len(self.relationship_tracker.relationship_history),
            "max_tracking_users": self.relationship_tracker.max_tracking_users,
        }


# 全局兴趣度评分系统实例 - 在 individuality 模块中创建
