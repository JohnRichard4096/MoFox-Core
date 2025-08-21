import json
import asyncio
import random
from datetime import datetime, time, timedelta
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, ValidationError, validator

from src.common.database.sqlalchemy_models import Schedule, get_db_session
from src.common.database.monthly_plan_db import get_active_plans_for_month, soft_delete_plans
from src.config.config import global_config, model_config
from src.llm_models.utils_model import LLMRequest
from src.common.logger import get_logger
from json_repair import repair_json
from src.manager.async_task_manager import AsyncTask, async_task_manager


logger = get_logger("schedule_manager")

# 默认的日程生成指导原则
DEFAULT_SCHEDULE_GUIDELINES = """
我希望你每天都能过得充实而有趣。
请确保你的日程里有学习新知识的时间，这是你成长的关键。
但也不要忘记放松，可以看看视频、听听音乐或者玩玩游戏。
晚上我希望你能多和朋友们交流，维系好彼此的关系。
另外，请保证充足的休眠时间来处理和整合一天的数据。
"""

class ScheduleItem(BaseModel):
    """单个日程项的Pydantic模型"""
    time_range: str
    activity: str
    
    @validator('time_range')
    def validate_time_range(cls, v):
        """验证时间范围格式"""
        if not v or '-' not in v:
            raise ValueError("时间范围必须包含'-'分隔符")
        
        try:
            start_str, end_str = v.split('-', 1)
            start_str = start_str.strip()
            end_str = end_str.strip()
            
            # 验证时间格式
            datetime.strptime(start_str, "%H:%M")
            datetime.strptime(end_str, "%H:%M")
            
            return v
        except ValueError as e:
            raise ValueError(f"时间格式无效，应为HH:MM-HH:MM格式: {e}") from e
    
    @validator('activity')
    def validate_activity(cls, v):
        """验证活动描述"""
        if not v or not v.strip():
            raise ValueError("活动描述不能为空")
        return v.strip()

class ScheduleData(BaseModel):
    """完整日程数据的Pydantic模型"""
    schedule: List[ScheduleItem]
    
    @validator('schedule')
    def validate_schedule_completeness(cls, v):
        """验证日程是否覆盖24小时"""
        if not v:
            raise ValueError("日程不能为空")
        
        # 收集所有时间段
        time_ranges = []
        for item in v:
            try:
                start_str, end_str = item.time_range.split('-', 1)
                start_time = datetime.strptime(start_str.strip(), "%H:%M").time()
                end_time = datetime.strptime(end_str.strip(), "%H:%M").time()
                time_ranges.append((start_time, end_time))
            except ValueError:
                continue
        
        # 检查是否覆盖24小时
        if not cls._check_24_hour_coverage(time_ranges):
            raise ValueError("日程必须覆盖完整的24小时")
        
        return v
    
    @staticmethod
    def _check_24_hour_coverage(time_ranges: List[tuple]) -> bool:
        """检查时间段是否覆盖24小时"""
        if not time_ranges:
            return False
        
        # 将时间转换为分钟数进行计算
        def time_to_minutes(t: time) -> int:
            return t.hour * 60 + t.minute
        
        # 创建覆盖情况数组 (1440分钟 = 24小时)
        covered = [False] * 1440
        
        for start_time, end_time in time_ranges:
            start_min = time_to_minutes(start_time)
            end_min = time_to_minutes(end_time)
            
            if start_min <= end_min:
                # 同一天内的时间段
                for i in range(start_min, end_min):
                    if i < 1440:
                        covered[i] = True
            else:
                # 跨天的时间段
                for i in range(start_min, 1440):
                    covered[i] = True
                for i in range(0, end_min):
                    covered[i] = True
        
        # 检查是否所有分钟都被覆盖
        return all(covered)

class ScheduleManager:
    def __init__(self):
        self.today_schedule: Optional[List[Dict[str, Any]]] = None
        self.llm = LLMRequest(model_set=model_config.model_task_config.schedule_generator, request_type="schedule")
        self.max_retries = 3  # 最大重试次数
        self.daily_task_started = False

    async def start_daily_schedule_generation(self):
        """启动每日零点自动生成新日程的任务"""
        if not self.daily_task_started:
            logger.info("正在启动每日日程生成任务...")
            task = DailyScheduleGenerationTask(self)
            await async_task_manager.add_task(task)
            self.daily_task_started = True
            logger.info("每日日程生成任务已成功启动。")
        else:
            logger.info("每日日程生成任务已在运行中。")

    async def load_or_generate_today_schedule(self):
        # 检查是否启用日程管理功能
        if not global_config.schedule.enable:
            logger.info("日程管理功能已禁用，跳过日程加载和生成。")
            return

        today_str = datetime.now().strftime("%Y-%m-%d")
        try:
            with get_db_session() as session:
                schedule_record = session.query(Schedule).filter(Schedule.date == today_str).first()
                if schedule_record:
                    logger.info(f"从数据库加载今天的日程 ({today_str})。")
                    
                    try:
                        schedule_data = json.loads(str(schedule_record.schedule_data))
                        
                        # 使用Pydantic验证日程数据
                        if self._validate_schedule_with_pydantic(schedule_data):
                            self.today_schedule = schedule_data
                            schedule_str = f"已成功加载今天的日程 ({today_str})：\n"
                            if self.today_schedule:
                                for item in self.today_schedule:
                                    schedule_str += f"  - {item.get('time_range', '未知时间')}: {item.get('activity', '未知活动')}\n"
                            logger.info(schedule_str)
                        else:
                            logger.warning("数据库中的日程数据格式无效，将重新生成日程")
                            await self.generate_and_save_schedule()
                    except json.JSONDecodeError as e:
                        logger.error(f"日程数据JSON解析失败: {e}，将重新生成日程")
                        await self.generate_and_save_schedule()
                else:
                    logger.info(f"数据库中未找到今天的日程 ({today_str})，将调用 LLM 生成。")
                    await self.generate_and_save_schedule()
        except Exception as e:
            logger.error(f"加载或生成日程时出错: {e}")

    async def generate_and_save_schedule(self):
        now = datetime.now()
        today_str = now.strftime("%Y-%m-%d")
        current_month_str = now.strftime("%Y-%m")
        weekday = now.strftime("%A")

        # 获取月度计划作为额外参考
        monthly_plans_block = ""
        used_plan_ids = []
        if global_config.monthly_plan_system and global_config.monthly_plan_system.enable:
            active_plans = get_active_plans_for_month(current_month_str)
            if active_plans:
                # 随机抽取最多3个计划
                num_to_sample = min(len(active_plans), 3)
                sampled_plans = random.sample(active_plans, num_to_sample)
                used_plan_ids = [p.id for p in sampled_plans]  # type: ignore
                
                plan_texts = "\n".join([f"- {p.plan_text}" for p in sampled_plans])
                monthly_plans_block = f"""
**我这个月的一些小目标/计划 (请在今天的日程中适当体现)**:
{plan_texts}
"""

        guidelines = global_config.schedule.guidelines or DEFAULT_SCHEDULE_GUIDELINES
        personality = global_config.personality.personality_core
        personality_side = global_config.personality.personality_side

        prompt = f"""
我，{global_config.bot.nickname}，需要为自己规划一份今天（{today_str}，星期{weekday}）的详细日程安排。

**关于我**:
- **核心人设**: {personality}
- **具体习惯与兴趣**:
{personality_side}
{monthly_plans_block}
**我今天的规划原则**:
{guidelines}

**重要要求**:
1. 必须返回一个完整的、有效的JSON数组格式
2. 数组中的每个对象都必须包含 "time_range" 和 "activity" 两个键
3. 时间范围必须覆盖全部24小时，不能有遗漏
4. time_range格式必须为 "HH:MM-HH:MM" (24小时制)
5. 相邻的时间段必须连续，不能有间隙
6. 不要包含任何JSON以外的解释性文字或代码块标记

**示例**:
[
    {{"time_range": "00:00-07:00", "activity": "进入梦乡，处理数据"}},
    {{"time_range": "07:00-08:00", "activity": "起床伸个懒腰，看看今天有什么新闻"}},
    {{"time_range": "08:00-09:00", "activity": "享用早餐，规划今天的任务"}}
]

请你扮演我，以我的身份和口吻，为我生成一份完整的24小时日程表。
"""
        
        # 尝试生成并验证日程，最多重试max_retries次
        for attempt in range(self.max_retries):
            try:
                logger.info(f"正在生成日程 (尝试 {attempt + 1}/{self.max_retries})")
                response, _ = await self.llm.generate_response_async(prompt)
                schedule_data = json.loads(repair_json(response))
                
                # 使用Pydantic验证生成的日程数据
                if self._validate_schedule_with_pydantic(schedule_data):
                    # 验证通过，保存到数据库
                    with get_db_session() as session:
                        # 检查是否已存在今天的日程
                        existing_schedule = session.query(Schedule).filter(Schedule.date == today_str).first()
                        if existing_schedule:
                            # 更新现有日程
                            session.query(Schedule).filter(Schedule.date == today_str).update({
                                Schedule.schedule_data: json.dumps(schedule_data),
                                Schedule.updated_at: datetime.now()
                            })
                        else:
                            # 创建新日程
                            new_schedule = Schedule(
                                date=today_str,
                                schedule_data=json.dumps(schedule_data)
                            )
                            session.add(new_schedule)
                        session.commit()
                    
                    # 美化输出
                    schedule_str = f"已成功生成并保存今天的日程 ({today_str})：\n"
                    for item in schedule_data:
                        schedule_str += f"  - {item.get('time_range', '未知时间')}: {item.get('activity', '未知活动')}\n"
                    logger.info(schedule_str)
                    
                    self.today_schedule = schedule_data
                    
                    # 成功生成日程后，根据概率软删除使用过的月度计划
                    if used_plan_ids and global_config.monthly_plan_system:
                        if random.random() < global_config.monthly_plan_system.deletion_probability_on_use:
                            logger.info(f"根据概率，将使用过的月度计划 {used_plan_ids} 标记为已完成。")
                            soft_delete_plans(used_plan_ids)
                            
                    return
                else:
                    logger.warning(f"第 {attempt + 1} 次生成的日程验证失败，正在重试...")
                    if attempt < self.max_retries - 1:
                        # 在重试时添加更详细的错误提示
                        prompt += "\n\n**上次生成失败，请特别注意**:\n- 确保所有时间段连续覆盖24小时\n- 时间格式必须为HH:MM-HH:MM\n- 不能有时间间隙或重叠"
                        
            except Exception as e:
                logger.error(f"第 {attempt + 1} 次生成日程失败: {e}")
                if attempt == self.max_retries - 1:
                    logger.error(f"经过 {self.max_retries} 次尝试，仍无法生成有效日程")

    def get_current_activity(self) -> Optional[str]:
        # 检查是否启用日程管理功能
        if not global_config.schedule.enable:
            return None

        if not self.today_schedule:
            return None

        now = datetime.now().time()
        for event in self.today_schedule:
            try:
                time_range = event.get("time_range")
                activity = event.get("activity")
                
                if not time_range or not activity:
                    logger.warning(f"日程事件缺少必要字段: {event}")
                    continue
                    
                start_str, end_str = time_range.split('-')
                start_time = datetime.strptime(start_str.strip(), "%H:%M").time()
                end_time = datetime.strptime(end_str.strip(), "%H:%M").time()

                if start_time <= end_time:
                    if start_time <= now < end_time:
                        return activity
                else:  # 跨天事件
                    if now >= start_time or now < end_time:
                        return activity
            except (ValueError, KeyError, AttributeError) as e:
                logger.warning(f"解析日程事件失败: {event}, 错误: {e}")
                continue
        return None

    def is_sleeping(self) -> bool:
        """检查当前是否处于休眠时间（日程表的第一项或最后一项）"""
        if not global_config.schedule.enabe_is_sleep:
            return False
        if not self.today_schedule:
            return False

        now = datetime.now().time()
        
        # 修复：应该获取列表的第一个元素
        first_item = self.today_schedule
        last_item = self.today_schedule[-1]

        for item in [first_item, last_item]:
            try:
                time_range = item.get("time_range")
                if not time_range:
                    continue

                start_str, end_str = time_range.split('-')
                start_time = datetime.strptime(start_str.strip(), "%H:%M").time()
                end_time = datetime.strptime(end_str.strip(), "%H:%M").time()

                if start_time <= end_time:
                    # 同一天内的时间段
                    if start_time <= now < end_time:
                        return True
                else:
                    # 跨天的时间段
                    if now >= start_time or now < end_time:
                        return True
            except (ValueError, KeyError, AttributeError) as e:
                logger.warning(f"解析休眠日程事件失败: {item}, 错误: {e}")
                continue
        
        return False

    def _validate_schedule_with_pydantic(self, schedule_data) -> bool:
        """使用Pydantic验证日程数据格式和完整性"""
        try:
            # 尝试用Pydantic模型验证
            ScheduleData(schedule=schedule_data)
            logger.info("日程数据Pydantic验证通过")
            return True
        except ValidationError as e:
            logger.warning(f"日程数据Pydantic验证失败: {e}")
            return False
        except Exception as e:
            logger.error(f"日程数据验证时发生异常: {e}")
            return False

    def _validate_schedule_data(self, schedule_data) -> bool:
        """保留原有的基础验证方法作为备用"""
        if not isinstance(schedule_data, list):
            logger.warning("日程数据不是列表格式")
            return False
        
        for item in schedule_data:
            if not isinstance(item, dict):
                logger.warning(f"日程项不是字典格式: {item}")
                return False
            
            if 'time_range' not in item or 'activity' not in item:
                logger.warning(f"日程项缺少必要字段 (time_range 或 activity): {item}")
                return False
                
            if not isinstance(item['time_range'], str) or not isinstance(item['activity'], str):
                logger.warning(f"日程项字段类型不正确: {item}")
                return False
        
        return True


class DailyScheduleGenerationTask(AsyncTask):
    """每日零点自动生成新日程的任务"""

    def __init__(self, schedule_manager: "ScheduleManager"):
        super().__init__(task_name="DailyScheduleGenerationTask")
        self.schedule_manager = schedule_manager

    async def run(self):
        while True:
            try:
                # 1. 计算到下一个零点的时间
                now = datetime.now()
                tomorrow = now.date() + timedelta(days=1)
                midnight = datetime.combine(tomorrow, time.min)
                sleep_seconds = (midnight - now).total_seconds()

                logger.info(f"下一次日程生成任务将在 {sleep_seconds:.2f} 秒后运行 (北京时间 {midnight.strftime('%Y-%m-%d %H:%M:%S')})")
                
                # 2. 等待直到零点
                await asyncio.sleep(sleep_seconds)

                # 3. 执行日程生成
                logger.info("到达每日零点，开始为新的一天生成日程...")
                await self.schedule_manager.generate_and_save_schedule()
                
            except asyncio.CancelledError:
                logger.info("每日日程生成任务被取消。")
                break
            except Exception as e:
                logger.error(f"每日日程生成任务发生未知错误: {e}")
                # 发生错误后，等待5分钟再重试，避免频繁失败
                await asyncio.sleep(300)


schedule_manager = ScheduleManager()