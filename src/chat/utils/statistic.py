import asyncio
from collections import defaultdict
from datetime import datetime, timedelta
from typing import Any

from src.common.database.compatibility import db_get, db_query
from src.common.database.api.query import QueryBuilder
from src.common.database.core.models import LLMUsage, Messages, OnlineTime
from src.common.logger import get_logger
from src.manager.async_task_manager import AsyncTask
from src.manager.local_store_manager import local_storage

logger = get_logger("maibot_statistic")

# 统计查询的批次大小
STAT_BATCH_SIZE = 2000
# 内存优化：单次统计最大处理记录数（防止极端情况）
STAT_MAX_RECORDS = 100000

# 彻底异步化：删除原同步包装器 _sync_db_get，所有数据库访问统一使用 await db_get。


from .report_generator import HTMLReportGenerator
from .statistic_keys import *


class OnlineTimeRecordTask(AsyncTask):
    """在线时间记录任务"""

    def __init__(self):
        super().__init__(task_name="Online Time Record Task", run_interval=60)

        self.record_id: int | None = None
        """记录ID"""

    async def run(self):  # sourcery skip: use-named-expression
        try:
            current_time = datetime.now()
            extended_end_time = current_time + timedelta(minutes=1)

            if self.record_id:
                # 如果有记录，则更新结束时间
                updated_rows = await db_query(
                    model_class=OnlineTime,
                    query_type="update",
                    filters={"id": self.record_id},
                    data={"end_timestamp": extended_end_time},
                )
                if updated_rows == 0:
                    # Record might have been deleted or ID is stale, try to find/create
                    self.record_id = None

            if not self.record_id:
                # 查找最近一分钟内的记录
                recent_threshold = current_time - timedelta(minutes=1)
                recent_records = await db_get(
                    model_class=OnlineTime,
                    filters={"end_timestamp": {"$gte": recent_threshold}},
                    order_by="-end_timestamp",
                    limit=1,
                    single_result=True,
                )

                if recent_records:
                    # 找到近期记录，更新它
                    record_to_use = recent_records[0] if isinstance(recent_records, list) else recent_records
                    self.record_id = record_to_use.get("id")
                    if self.record_id:
                        await db_query(
                            model_class=OnlineTime,
                            query_type="update",
                            filters={"id": self.record_id},
                            data={"end_timestamp": extended_end_time},
                        )
                else:
                    # 创建新记录
                    new_record = await db_query(
                        model_class=OnlineTime,
                        query_type="create",
                        data={
                            "timestamp": str(current_time),
                            "duration": 5,  # 初始时长为5分钟
                            "start_timestamp": current_time,
                            "end_timestamp": extended_end_time,
                        },
                    )
                    if new_record:
                        record_to_use = new_record[0] if isinstance(new_record, list) else new_record
                        self.record_id = record_to_use.get("id")
        except Exception as e:
            logger.error(f"在线时间记录失败，错误信息：{e}")


def _format_online_time(online_seconds: int) -> str:
    """
    格式化在线时间
    :param online_seconds: 在线时间（秒）
    :return: 格式化后的在线时间字符串
    """
    total_online_time = timedelta(seconds=online_seconds)

    days = total_online_time.days
    hours = total_online_time.seconds // 3600
    minutes = (total_online_time.seconds // 60) % 60
    seconds = total_online_time.seconds % 60
    if days > 0:
        # 如果在线时间超过1天，则格式化为"X天X小时X分钟"
        return f"{total_online_time.days}天{hours}小时{minutes}分钟{seconds}秒"
    elif hours > 0:
        # 如果在线时间超过1小时，则格式化为"X小时X分钟X秒"
        return f"{hours}小时{minutes}分钟{seconds}秒"
    else:
        # 其他情况格式化为"X分钟X秒"
        return f"{minutes}分钟{seconds}秒"


class StatisticOutputTask(AsyncTask):
    """统计输出任务"""

    SEP_LINE = "-" * 84

    def __init__(self, record_file_path: str = "mofox_bot_statistics.html"):
        # 延迟300秒启动，运行间隔300秒
        super().__init__(task_name="Statistics Data Output Task", wait_before_start=0, run_interval=300)

        self.name_mapping: dict[str, tuple[str, float]] = {}
        """
            联系人/群聊名称映射 {聊天ID: (联系人/群聊名称, 记录时间（timestamp）)}
            注：设计记录时间的目的是方便更新名称，使联系人/群聊名称保持最新
        """

        self.record_file_path: str = record_file_path
        """
        记录文件路径
        """

        now = datetime.now()
        deploy_time_ts = local_storage.get("deploy_time")
        if deploy_time_ts:
            # 如果存在部署时间，则使用该时间作为全量统计的起始时间
            deploy_time = datetime.fromtimestamp(deploy_time_ts)  # type: ignore
        else:
            # 否则，使用最大时间范围，并记录部署时间为当前时间
            deploy_time = datetime(2000, 1, 1)
            local_storage["deploy_time"] = now.timestamp()
        self.stat_period: list[tuple[str, timedelta, str]] = [
            ("all_time", now - deploy_time, "自部署以来"),  # 必须保留"all_time"
            ("last_7_days", timedelta(days=7), "最近7天"),
            ("last_24_hours", timedelta(days=1), "最近24小时"),
            ("last_3_hours", timedelta(hours=3), "最近3小时"),
            ("last_hour", timedelta(hours=1), "最近1小时"),
        ]
        """
        统计时间段 [(统计名称, 统计时间段, 统计描述), ...]
        """

    def _statistic_console_output(self, stats: dict[str, Any], now: datetime):
        """
        输出统计数据到控制台
        :param stats: 统计数据
        :param now: 基准当前时间
        """
        # 输出最近一小时的统计数据
        output = [
            self.SEP_LINE,
            f"  最近1小时的统计数据  (自{now.strftime('%Y-%m-%d %H:%M:%S')}开始，详细信息见文件：{self.record_file_path})",
            self.SEP_LINE,
            self._format_total_stat(stats["last_hour"]),
            "",
            self._format_model_classified_stat(stats["last_hour"]),
            "",
            self._format_chat_stat(stats["last_hour"]),
            self.SEP_LINE,
            "",
        ]

        logger.info("\n" + "\n".join(output))

    @staticmethod
    async def _yield_control(iteration: int, interval: int = 200) -> None:
        """
        �ڴ����������ʱ������������첽�¼�ѭ�����Ӧ

        Args:
            iteration: ��ǰ�������
            interval: ÿ�����ٴ��л�һ��
        """
        if iteration % interval == 0:
            await asyncio.sleep(0)

    async def run(self):
        try:
            now = datetime.now()
            logger.info("正在收集统计数据(异步)...")
            stats = await self._collect_all_statistics(now)
            logger.info("统计数据收集完成")

            self._statistic_console_output(stats, now)
            # 使用新的 HTMLReportGenerator 生成报告
            chart_data = await self._collect_chart_data(stats)
            deploy_time = datetime.fromtimestamp(float(local_storage.get("deploy_time", now.timestamp())))  # type: ignore
            report_generator = HTMLReportGenerator(
                name_mapping=self.name_mapping,
                stat_period=self.stat_period,
                deploy_time=deploy_time,
            )
            await report_generator.generate_report(stats, chart_data, now, self.record_file_path)
            logger.info("统计数据HTML报告输出完成")

        except Exception as e:
            logger.exception(f"输出统计数据过程中发生异常，错误信息：{e}")

    async def run_async_background(self):
        """
        备选方案：完全异步后台运行统计输出
        使用此方法可以让统计任务完全非阻塞
        """

        async def _async_collect_and_output():
            try:
                now = datetime.now()
                logger.info("(后台) 正在收集统计数据(异步)...")
                stats = await self._collect_all_statistics(now)
                self._statistic_console_output(stats, now)

                # 使用新的 HTMLReportGenerator 生成报告
                chart_data = await self._collect_chart_data(stats)
                deploy_time = datetime.fromtimestamp(float(local_storage.get("deploy_time", now.timestamp())))  # type: ignore
                report_generator = HTMLReportGenerator(
                    name_mapping=self.name_mapping,
                    stat_period=self.stat_period,
                    deploy_time=deploy_time,
                )
                await report_generator.generate_report(stats, chart_data, now, self.record_file_path)

                logger.info("统计数据后台输出完成")
            except Exception as e:
                logger.exception(f"后台统计数据输出过程中发生异常：{e}")

        # 创建后台任务，立即返回
        asyncio.create_task(_async_collect_and_output())  # noqa: RUF006
    # -- 以下为统计数据收集方法 --

    @staticmethod
    async def _collect_model_request_for_period(collect_period: list[tuple[str, datetime]]) -> dict[str, Any]:
        """
        收集指定时间段的LLM请求统计数据

        :param collect_period: 统计时间段
        """
        if not collect_period:
            return {}

        # 排序-按照时间段开始时间降序排列（最晚的时间段在前）
        collect_period.sort(key=lambda x: x[1], reverse=True)

        stats = {
            period_key: {
                TOTAL_REQ_CNT: 0,
                REQ_CNT_BY_TYPE: defaultdict(int),
                REQ_CNT_BY_USER: defaultdict(int),
                REQ_CNT_BY_MODEL: defaultdict(int),
                REQ_CNT_BY_MODULE: defaultdict(int),
                REQ_CNT_BY_PROVIDER: defaultdict(int),  # New
                IN_TOK_BY_TYPE: defaultdict(int),
                IN_TOK_BY_USER: defaultdict(int),
                IN_TOK_BY_MODEL: defaultdict(int),
                IN_TOK_BY_MODULE: defaultdict(int),
                OUT_TOK_BY_TYPE: defaultdict(int),
                OUT_TOK_BY_USER: defaultdict(int),
                OUT_TOK_BY_MODEL: defaultdict(int),
                OUT_TOK_BY_MODULE: defaultdict(int),
                TOTAL_TOK_BY_TYPE: defaultdict(int),
                TOTAL_TOK_BY_USER: defaultdict(int),
                TOTAL_TOK_BY_MODEL: defaultdict(int),
                TOTAL_TOK_BY_MODULE: defaultdict(int),
                TOTAL_TOK_BY_PROVIDER: defaultdict(int),  # New
                TOTAL_COST: 0.0,
                COST_BY_TYPE: defaultdict(float),
                COST_BY_USER: defaultdict(float),
                COST_BY_MODEL: defaultdict(float),
                COST_BY_MODULE: defaultdict(float),
                COST_BY_PROVIDER: defaultdict(float),  # New
                TIME_COST_BY_TYPE: defaultdict(list),
                TIME_COST_BY_USER: defaultdict(list),
                TIME_COST_BY_MODEL: defaultdict(list),
                TIME_COST_BY_MODULE: defaultdict(list),
                TIME_COST_BY_PROVIDER: defaultdict(list),  # New
                AVG_TIME_COST_BY_TYPE: defaultdict(float),
                AVG_TIME_COST_BY_USER: defaultdict(float),
                AVG_TIME_COST_BY_MODEL: defaultdict(float),
                AVG_TIME_COST_BY_MODULE: defaultdict(float),
                STD_TIME_COST_BY_TYPE: defaultdict(float),
                STD_TIME_COST_BY_USER: defaultdict(float),
                STD_TIME_COST_BY_MODEL: defaultdict(float),
                STD_TIME_COST_BY_MODULE: defaultdict(float),
                AVG_TIME_COST_BY_PROVIDER: defaultdict(float),
                STD_TIME_COST_BY_PROVIDER: defaultdict(float),
                # New calculated fields
                TPS_BY_MODEL: defaultdict(float),
                COST_PER_KTOK_BY_MODEL: defaultdict(float),
                AVG_TOK_BY_MODEL: defaultdict(float),
                TPS_BY_PROVIDER: defaultdict(float),
                COST_PER_KTOK_BY_PROVIDER: defaultdict(float),
                # Chart data
                PIE_CHART_COST_BY_PROVIDER: {},
                PIE_CHART_REQ_BY_PROVIDER: {},
                PIE_CHART_COST_BY_MODULE: {},
                BAR_CHART_COST_BY_MODEL: {},
                BAR_CHART_REQ_BY_MODEL: {},
                BAR_CHART_TOKEN_COMPARISON: {},
                SCATTER_CHART_RESPONSE_TIME: {},
                RADAR_CHART_MODEL_EFFICIENCY: {},
                HEATMAP_CHAT_ACTIVITY: {},
                DOUGHNUT_CHART_PROVIDER_REQUESTS: {},
                LINE_CHART_COST_TREND: {},
                BAR_CHART_AVG_RESPONSE_TIME: {},
            }
            for period_key, _ in collect_period
        }

        # 以最早的时间戳为起始时间获取记录
        # 🔧 内存优化：使用分批查询代替全量加载
        query_start_time = collect_period[-1][1]
        
        query_builder = (
            QueryBuilder(LLMUsage)
            .no_cache()
            .filter(timestamp__gte=query_start_time)
            .order_by("-timestamp")
        )
        
        total_processed = 0
        async for batch in query_builder.iter_batches(batch_size=STAT_BATCH_SIZE, as_dict=True):
            for record in batch:
                if total_processed >= STAT_MAX_RECORDS:
                    logger.warning(f"统计处理记录数达到上限 {STAT_MAX_RECORDS}，跳过剩余记录")
                    break
                    
                if not isinstance(record, dict):
                    continue

                record_timestamp = record.get("timestamp")
                if isinstance(record_timestamp, str):
                    record_timestamp = datetime.fromisoformat(record_timestamp)

                if not record_timestamp:
                    continue

                for period_idx, (_, period_start) in enumerate(collect_period):
                    if record_timestamp >= period_start:
                        for period_key, _ in collect_period[period_idx:]:
                            stats[period_key][TOTAL_REQ_CNT] += 1

                            request_type = record.get("request_type") or "unknown"
                            user_id = record.get("user_id") or "unknown"
                            model_name = record.get("model_name") or "unknown"
                            provider_name = record.get("model_api_provider") or "unknown"

                            # 提取模块名：如果请求类型包含"."，取第一个"."之前的部分
                            module_name = request_type.split(".")[0] if "." in request_type else request_type

                            stats[period_key][REQ_CNT_BY_TYPE][request_type] += 1
                            stats[period_key][REQ_CNT_BY_USER][user_id] += 1
                            stats[period_key][REQ_CNT_BY_MODEL][model_name] += 1
                            stats[period_key][REQ_CNT_BY_MODULE][module_name] += 1
                            stats[period_key][REQ_CNT_BY_PROVIDER][provider_name] += 1

                            prompt_tokens = record.get("prompt_tokens") or 0
                            completion_tokens = record.get("completion_tokens") or 0
                            total_tokens = prompt_tokens + completion_tokens

                            stats[period_key][IN_TOK_BY_TYPE][request_type] += prompt_tokens
                            stats[period_key][IN_TOK_BY_USER][user_id] += prompt_tokens
                            stats[period_key][IN_TOK_BY_MODEL][model_name] += prompt_tokens
                            stats[period_key][IN_TOK_BY_MODULE][module_name] += prompt_tokens

                            stats[period_key][OUT_TOK_BY_TYPE][request_type] += completion_tokens
                            stats[period_key][OUT_TOK_BY_USER][user_id] += completion_tokens
                            stats[period_key][OUT_TOK_BY_MODEL][model_name] += completion_tokens
                            stats[period_key][OUT_TOK_BY_MODULE][module_name] += completion_tokens

                            stats[period_key][TOTAL_TOK_BY_TYPE][request_type] += total_tokens
                            stats[period_key][TOTAL_TOK_BY_USER][user_id] += total_tokens
                            stats[period_key][TOTAL_TOK_BY_MODEL][model_name] += total_tokens
                            stats[period_key][TOTAL_TOK_BY_MODULE][module_name] += total_tokens
                            stats[period_key][TOTAL_TOK_BY_PROVIDER][provider_name] += total_tokens

                            cost = record.get("cost") or 0.0
                            stats[period_key][TOTAL_COST] += cost
                            stats[period_key][COST_BY_TYPE][request_type] += cost
                            stats[period_key][COST_BY_USER][user_id] += cost
                            stats[period_key][COST_BY_MODEL][model_name] += cost
                            stats[period_key][COST_BY_MODULE][module_name] += cost
                            stats[period_key][COST_BY_PROVIDER][provider_name] += cost

                            # 收集time_cost数据
                            time_cost = record.get("time_cost") or 0.0
                            if time_cost > 0:  # 只记录有效的time_cost
                                stats[period_key][TIME_COST_BY_TYPE][request_type].append(time_cost)
                                stats[period_key][TIME_COST_BY_USER][user_id].append(time_cost)
                                stats[period_key][TIME_COST_BY_MODEL][model_name].append(time_cost)
                                stats[period_key][TIME_COST_BY_MODULE][module_name].append(time_cost)
                                stats[period_key][TIME_COST_BY_PROVIDER][provider_name].append(time_cost)
                        break

                total_processed += 1
                if total_processed % 500 == 0:
                    await StatisticOutputTask._yield_control(total_processed, interval=1)
            
            # 检查是否达到上限
            if total_processed >= STAT_MAX_RECORDS:
                break
            
            # 每批处理完后让出控制权
            await asyncio.sleep(0)
        # -- 计算派生指标 --
        for period_key, period_stats in stats.items():
            # 计算模型相关指标
            for model_idx, (model_name, req_count) in enumerate(period_stats[REQ_CNT_BY_MODEL].items(), 1):
                total_tok = period_stats[TOTAL_TOK_BY_MODEL][model_name] or 0
                total_cost = period_stats[COST_BY_MODEL][model_name] or 0
                time_costs = period_stats[TIME_COST_BY_MODEL][model_name] or []
                total_time_cost = sum(time_costs)

                # TPS
                if total_time_cost > 0:
                    period_stats[TPS_BY_MODEL][model_name] = round(total_tok / total_time_cost, 2)
                # Cost per 1K Tokens
                if total_tok > 0:
                    period_stats[COST_PER_KTOK_BY_MODEL][model_name] = round((total_cost / total_tok) * 1000, 4)
                # Avg Tokens per Request
                period_stats[AVG_TOK_BY_MODEL][model_name] = round(total_tok / req_count) if req_count > 0 else 0

                await StatisticOutputTask._yield_control(model_idx, interval=100)

            # 计算供应商相关指标
            for provider_idx, (provider_name, req_count) in enumerate(period_stats[REQ_CNT_BY_PROVIDER].items(), 1):
                total_tok = period_stats[TOTAL_TOK_BY_PROVIDER][provider_name]
                total_cost = period_stats[COST_BY_PROVIDER][provider_name]
                time_costs = period_stats[TIME_COST_BY_PROVIDER][provider_name]
                total_time_cost = sum(time_costs)

                # TPS
                if total_time_cost > 0:
                    period_stats[TPS_BY_PROVIDER][provider_name] = round(total_tok / total_time_cost, 2)
                # Cost per 1K Tokens
                if total_tok > 0:
                    period_stats[COST_PER_KTOK_BY_PROVIDER][provider_name] = round((total_cost / total_tok) * 1000, 4)

                await StatisticOutputTask._yield_control(provider_idx, interval=100)

            # 计算平均耗时和标准差
            for category_key, items in [
                (REQ_CNT_BY_USER, "user"),
                (REQ_CNT_BY_MODEL, "model"),
                (REQ_CNT_BY_MODULE, "module"),
                (REQ_CNT_BY_PROVIDER, "provider"),
            ]:
                time_cost_key = f"time_costs_by_{items.lower()}"
                avg_key = f"avg_time_costs_by_{items.lower()}"
                std_key = f"std_time_costs_by_{items.lower()}"
                for idx, item_name in enumerate(period_stats[category_key], 1):
                    time_costs = period_stats[time_cost_key][item_name]
                    if time_costs:
                        avg_time = sum(time_costs) / len(time_costs)
                        period_stats[avg_key][item_name] = round(avg_time, 3)
                        if len(time_costs) > 1:
                            variance = sum((x - avg_time) ** 2 for x in time_costs) / len(time_costs)
                            period_stats[std_key][item_name] = round(variance**0.5, 3)
                        else:
                            period_stats[std_key][item_name] = 0.0
                    else:
                        period_stats[avg_key][item_name] = 0.0
                        period_stats[std_key][item_name] = 0.0

                    await StatisticOutputTask._yield_control(idx, interval=200)

            # 准备图表数据
            # 按供应商花费饼图
            provider_costs = period_stats[COST_BY_PROVIDER]
            if provider_costs:
                sorted_providers = sorted(provider_costs.items(), key=lambda item: item[1], reverse=True)
                period_stats[PIE_CHART_COST_BY_PROVIDER] = {
                    "labels": [item[0] for item in sorted_providers],
                    "data": [round(item[1], 4) for item in sorted_providers],
                }

            # 按模块花费饼图
            module_costs = period_stats[COST_BY_MODULE]
            if module_costs:
                sorted_modules = sorted(module_costs.items(), key=lambda item: item[1], reverse=True)
                period_stats[PIE_CHART_COST_BY_MODULE] = {
                    "labels": [item[0] for item in sorted_modules],
                    "data": [round(item[1], 4) for item in sorted_modules],
                }

            # 按模型花费条形图
            model_costs = period_stats[COST_BY_MODEL]
            if model_costs:
                sorted_models = sorted(model_costs.items(), key=lambda item: item[1], reverse=True)
                period_stats[BAR_CHART_COST_BY_MODEL] = {
                    "labels": [item[0] for item in sorted_models],
                    "data": [round(item[1], 4) for item in sorted_models],
                }
            
            # 1. Token输入输出对比条形图
            model_names = list(period_stats[REQ_CNT_BY_MODEL].keys())
            if model_names:
                period_stats[BAR_CHART_TOKEN_COMPARISON] = {
                    "labels": model_names,
                    "input_tokens": [period_stats[IN_TOK_BY_MODEL].get(m, 0) for m in model_names],
                    "output_tokens": [period_stats[OUT_TOK_BY_MODEL].get(m, 0) for m in model_names],
                }
            
            # 2. 响应时间分布散点图数据（限制数据点以提高加载速度）
            scatter_data = []
            max_points_per_model = 50  # 每个模型最多50个点
            for model_name, time_costs in period_stats[TIME_COST_BY_MODEL].items():
                # 如果数据点太多，进行采样
                if len(time_costs) > max_points_per_model:
                    step = len(time_costs) // max_points_per_model
                    sampled_costs = time_costs[::step][:max_points_per_model]
                else:
                    sampled_costs = time_costs
                
                for idx, time_cost in enumerate(sampled_costs):
                    scatter_data.append({
                        "model": model_name,
                        "x": idx,
                        "y": round(time_cost, 3),
                        "tokens": period_stats[TOTAL_TOK_BY_MODEL].get(model_name, 0) // len(time_costs) if time_costs else 0
                    })
            period_stats[SCATTER_CHART_RESPONSE_TIME] = scatter_data
            
            # 3. 模型效率雷达图
            if model_names:
                # 取前5个最常用的模型
                top_models = sorted(period_stats[REQ_CNT_BY_MODEL].items(), key=lambda x: x[1], reverse=True)[:5]
                radar_data = []
                for model_name, _ in top_models:
                    # 归一化各项指标到0-100
                    req_count = period_stats[REQ_CNT_BY_MODEL].get(model_name, 0)
                    tps = period_stats[TPS_BY_MODEL].get(model_name, 0)
                    avg_time = period_stats[AVG_TIME_COST_BY_MODEL].get(model_name, 0)
                    cost_per_ktok = period_stats[COST_PER_KTOK_BY_MODEL].get(model_name, 0)
                    avg_tokens = period_stats[AVG_TOK_BY_MODEL].get(model_name, 0)
                    
                    # 简单的归一化（反向归一化时间和成本，值越小越好）
                    max_req = max([period_stats[REQ_CNT_BY_MODEL].get(m[0], 1) for m in top_models])
                    max_tps = max([period_stats[TPS_BY_MODEL].get(m[0], 1) for m in top_models])
                    max_time = max([period_stats[AVG_TIME_COST_BY_MODEL].get(m[0], 0.1) for m in top_models])
                    max_cost = max([period_stats[COST_PER_KTOK_BY_MODEL].get(m[0], 0.001) for m in top_models])
                    max_tokens = max([period_stats[AVG_TOK_BY_MODEL].get(m[0], 1) for m in top_models])
                    
                    radar_data.append({
                        "model": model_name,
                        "metrics": [
                            round((req_count / max_req) * 100, 2) if max_req > 0 else 0,  # 请求量
                            round((tps / max_tps) * 100, 2) if max_tps > 0 else 0,  # TPS
                            round((1 - avg_time / max_time) * 100, 2) if max_time > 0 else 100,  # 速度(反向)
                            round((1 - cost_per_ktok / max_cost) * 100, 2) if max_cost > 0 else 100,  # 成本效益(反向)
                            round((avg_tokens / max_tokens) * 100, 2) if max_tokens > 0 else 0,  # Token容量
                        ]
                    })
                period_stats[RADAR_CHART_MODEL_EFFICIENCY] = {
                    "labels": ["请求量", "TPS", "响应速度", "成本效益", "Token容量"],
                    "datasets": radar_data
                }
            
            # 4. 供应商请求占比环形图
            provider_requests = period_stats[REQ_CNT_BY_PROVIDER]
            if provider_requests:
                sorted_provider_reqs = sorted(provider_requests.items(), key=lambda item: item[1], reverse=True)
                period_stats[DOUGHNUT_CHART_PROVIDER_REQUESTS] = {
                    "labels": [item[0] for item in sorted_provider_reqs],
                    "data": [item[1] for item in sorted_provider_reqs],
                }
            
            # 5. 平均响应时间条形图
            if model_names:
                sorted_by_time = sorted(
                    [(m, period_stats[AVG_TIME_COST_BY_MODEL].get(m, 0)) for m in model_names],
                    key=lambda x: x[1],
                    reverse=True
                )
                period_stats[BAR_CHART_AVG_RESPONSE_TIME] = {
                    "labels": [item[0] for item in sorted_by_time],
                    "data": [round(item[1], 3) for item in sorted_by_time],
                }
        return stats

    @staticmethod
    async def _collect_online_time_for_period(
        collect_period: list[tuple[str, datetime]], now: datetime
    ) -> dict[str, Any]:
        """
        收集指定时间段的在线时间统计数据

        :param collect_period: 统计时间段
        """
        if not collect_period:
            return {}

        collect_period.sort(key=lambda x: x[1], reverse=True)

        stats = {
            period_key: {
                ONLINE_TIME: 0.0,
            }
            for period_key, _ in collect_period
        }

        query_start_time = collect_period[-1][1]
        # 🔧 内存优化：使用分批查询
        query_builder = (
            QueryBuilder(OnlineTime)
            .no_cache()
            .filter(end_timestamp__gte=query_start_time)
            .order_by("-end_timestamp")
        )

        async for batch in query_builder.iter_batches(batch_size=STAT_BATCH_SIZE, as_dict=True):
            for record in batch:
                if not isinstance(record, dict):
                    continue

                record_end_timestamp = record.get("end_timestamp")
                if isinstance(record_end_timestamp, str):
                    record_end_timestamp = datetime.fromisoformat(record_end_timestamp)

                record_start_timestamp = record.get("start_timestamp")
                if isinstance(record_start_timestamp, str):
                    record_start_timestamp = datetime.fromisoformat(record_start_timestamp)

                if not record_end_timestamp or not record_start_timestamp:
                    continue

                for boundary_idx, (_, period_boundary_start) in enumerate(collect_period):
                    if record_end_timestamp >= period_boundary_start:
                        # Calculate effective end time for this record in relation to 'now'
                        effective_end_time = min(record_end_timestamp, now)

                        for period_key, current_period_start_time in collect_period[boundary_idx:]:
                            # Determine the portion of the record that falls within this specific statistical period
                            overlap_start = max(record_start_timestamp, current_period_start_time)
                            overlap_end = effective_end_time  # Already capped by 'now' and record's own end

                            if overlap_end > overlap_start:
                                stats[period_key][ONLINE_TIME] += (overlap_end - overlap_start).total_seconds()
                        break
            
            # 每批处理完后让出控制权
            await asyncio.sleep(0)

        return stats

    async def _collect_message_count_for_period(self, collect_period: list[tuple[str, datetime]]) -> dict[str, Any]:
        """
        收集指定时间段的消息统计数据

        :param collect_period: 统计时间段
        """
        if not collect_period:
            return {}

        collect_period.sort(key=lambda x: x[1], reverse=True)

        stats = {
            period_key: {
                TOTAL_MSG_CNT: 0,
                MSG_CNT_BY_CHAT: defaultdict(int),
            }
            for period_key, _ in collect_period
        }

        query_start_timestamp = collect_period[-1][1].timestamp()  # Messages.time is a DoubleField (timestamp)
        # 🔧 内存优化：使用分批查询
        query_builder = (
            QueryBuilder(Messages)
            .no_cache()
            .filter(time__gte=query_start_timestamp)
            .order_by("-time")
        )

        total_processed = 0
        async for batch in query_builder.iter_batches(batch_size=STAT_BATCH_SIZE, as_dict=True):
            for message in batch:
                if total_processed >= STAT_MAX_RECORDS:
                    logger.warning(f"消息统计处理记录数达到上限 {STAT_MAX_RECORDS}，跳过剩余记录")
                    break
                    
                if not isinstance(message, dict):
                    continue
                message_time_ts = message.get("time")  # This is a float timestamp

                if not message_time_ts:
                    continue

                chat_id = None
                chat_name = None

                # Logic based on SQLAlchemy model structure, aiming to replicate original intent
                if message.get("chat_info_group_id"):
                    chat_id = f"g{message['chat_info_group_id']}"
                    chat_name = message.get("chat_info_group_name") or f"群{message['chat_info_group_id']}"
                elif message.get("user_id"):  # Fallback to sender's info for chat_id if not a group_info based chat
                    # This uses the message SENDER's ID as per original logic's fallback
                    chat_id = f"u{message['user_id']}"  # SENDER's user_id
                    chat_name = message.get("user_nickname")  # SENDER's nickname
                else:
                    # If neither group_id nor sender_id is available for chat identification
                    continue

                if not chat_id:  # Should not happen if above logic is correct
                    continue

                # Update name_mapping
                if chat_name:
                    if chat_id in self.name_mapping:
                        if chat_name != self.name_mapping[chat_id][0] and message_time_ts > self.name_mapping[chat_id][1]:
                            self.name_mapping[chat_id] = (chat_name, message_time_ts)
                    else:
                        self.name_mapping[chat_id] = (chat_name, message_time_ts)
                for period_idx, (_, period_start_dt) in enumerate(collect_period):
                    if message_time_ts >= period_start_dt.timestamp():
                        for period_key, _ in collect_period[period_idx:]:
                            stats[period_key][TOTAL_MSG_CNT] += 1
                            stats[period_key][MSG_CNT_BY_CHAT][chat_id] += 1
                        break

                total_processed += 1
                if total_processed % 500 == 0:
                    await StatisticOutputTask._yield_control(total_processed, interval=1)
            
            # 检查是否达到上限
            if total_processed >= STAT_MAX_RECORDS:
                break
            
            # 每批处理完后让出控制权
            await asyncio.sleep(0)

        return stats

    async def _collect_all_statistics(self, now: datetime) -> dict[str, dict[str, Any]]:
        """
        收集各时间段的统计数据
        :param now: 基准当前时间
        """

        last_all_time_stat = None

        if "last_full_statistics" in local_storage:
            # 如果存在上次完整统计数据，则使用该数据进行增量统计
            last_stat: dict[str, Any] = local_storage["last_full_statistics"]  # 上次完整统计数据 # type: ignore

            self.name_mapping = last_stat["name_mapping"]  # 上次完整统计数据的名称映射
            last_all_time_stat = last_stat["stat_data"]  # 上次完整统计的统计数据
            last_stat_timestamp = datetime.fromtimestamp(last_stat["timestamp"])  # 上次完整统计数据的时间戳
            self.stat_period = [item for item in self.stat_period if item[0] != "all_time"]  # 删除"所有时间"的统计时段
            self.stat_period.append(("all_time", now - last_stat_timestamp, "自部署以来的"))

        stat_start_timestamp = [(period[0], now - period[1]) for period in self.stat_period]

        stat = {item[0]: {} for item in self.stat_period}

        model_req_stat, online_time_stat, message_count_stat = await asyncio.gather(
            self._collect_model_request_for_period(stat_start_timestamp),
            self._collect_online_time_for_period(stat_start_timestamp, now),
            self._collect_message_count_for_period(stat_start_timestamp),
        )

        # 统计数据合并
        # 合并三类统计数据
        for period_key, _ in stat_start_timestamp:
            stat[period_key].update(model_req_stat.get(period_key, {}))
            stat[period_key].update(online_time_stat.get(period_key, {}))
            stat[period_key].update(message_count_stat.get(period_key, {}))
        if last_all_time_stat:
            # 若存在上次完整统计数据，则将其与当前统计数据合并
            for key, val in last_all_time_stat.items():
                # If a key from old stats is not in the current period's stats, it means no new data was generated.
                # In this case, we carry over the old data.
                if key not in stat["all_time"]:
                    stat["all_time"][key] = val
                    continue

                # If the key exists in both, we merge.
                if isinstance(val, dict):
                    # It's a dictionary-like object (e.g., COST_BY_MODEL, TIME_COST_BY_TYPE)
                    current_dict = stat["all_time"][key]
                    for sub_key, sub_val in val.items():
                        if sub_key in current_dict:
                            current_val = current_dict[sub_key]
                            # 🔧 内存优化：处理压缩格式的 TIME_COST 数据
                            if isinstance(sub_val, dict) and "sum" in sub_val and "count" in sub_val:
                                # 压缩格式合并
                                if isinstance(current_val, dict) and "sum" in current_val:
                                    # 两边都是压缩格式
                                    current_dict[sub_key] = {
                                        "sum": current_val["sum"] + sub_val["sum"],
                                        "count": current_val["count"] + sub_val["count"],
                                        "sum_sq": current_val.get("sum_sq", 0) + sub_val.get("sum_sq", 0),
                                    }
                                elif isinstance(current_val, list):
                                    # 当前是列表，历史是压缩格式：先压缩当前再合并
                                    curr_sum = sum(current_val) if current_val else 0
                                    curr_count = len(current_val)
                                    curr_sum_sq = sum(v * v for v in current_val) if current_val else 0
                                    current_dict[sub_key] = {
                                        "sum": curr_sum + sub_val["sum"],
                                        "count": curr_count + sub_val["count"],
                                        "sum_sq": curr_sum_sq + sub_val.get("sum_sq", 0),
                                    }
                                else:
                                    # 未知情况，保留历史值
                                    current_dict[sub_key] = sub_val
                            elif isinstance(sub_val, list):
                                # 列表格式：extend（兼容旧数据，但新版不会产生这种情况）
                                if isinstance(current_val, list):
                                    current_dict[sub_key] = current_val + sub_val
                                else:
                                    current_dict[sub_key] = sub_val
                            else:
                                # 数值类型：直接相加
                                current_dict[sub_key] += sub_val
                        else:
                            current_dict[sub_key] = sub_val
                else:
                    # It's a simple value (e.g., TOTAL_COST)
                    stat["all_time"][key] += val

        # 更新上次完整统计数据的时间戳
        # 🔧 内存优化：在保存前压缩 TIME_COST 列表为聚合数据，避免无限增长
        compressed_stat_data = self._compress_time_cost_lists(stat["all_time"])
        # 将所有defaultdict转换为普通dict以避免类型冲突
        clean_stat_data = self._convert_defaultdict_to_dict(compressed_stat_data)
        local_storage["last_full_statistics"] = {
            "name_mapping": self.name_mapping,
            "stat_data": clean_stat_data,
            "timestamp": now.timestamp(),
        }

        return stat

    def _compress_time_cost_lists(self, data: dict[str, Any]) -> dict[str, Any]:
        """🔧 内存优化：将 TIME_COST_BY_* 的 list 压缩为聚合数据
        
        原始格式: {"model_a": [1.2, 2.3, 3.4, ...]}  (可能无限增长)
        压缩格式: {"model_a": {"sum": 6.9, "count": 3, "sum_sq": 18.29}}
        
        这样合并时只需要累加 sum/count/sum_sq，不会无限增长。
        avg = sum / count
        std = sqrt(sum_sq / count - (sum / count)^2)
        """
        # TIME_COST 相关的 key 前缀
        time_cost_keys = [
            TIME_COST_BY_TYPE, TIME_COST_BY_USER, TIME_COST_BY_MODEL,
            TIME_COST_BY_MODULE, TIME_COST_BY_PROVIDER
        ]
        
        result = dict(data)  # 浅拷贝
        
        for key in time_cost_keys:
            if key not in result:
                continue
            
            original = result[key]
            if not isinstance(original, dict):
                continue
            
            compressed = {}
            for sub_key, values in original.items():
                if isinstance(values, list):
                    # 原始列表格式，需要压缩
                    if values:
                        total = sum(values)
                        count = len(values)
                        sum_sq = sum(v * v for v in values)
                        compressed[sub_key] = {"sum": total, "count": count, "sum_sq": sum_sq}
                    else:
                        compressed[sub_key] = {"sum": 0.0, "count": 0, "sum_sq": 0.0}
                elif isinstance(values, dict) and "sum" in values and "count" in values:
                    # 已经是压缩格式，直接保留
                    compressed[sub_key] = values
                else:
                    # 未知格式，保留原值
                    compressed[sub_key] = values
            
            result[key] = compressed
        
        return result

    def _convert_defaultdict_to_dict(self, data):
        # sourcery skip: dict-comprehension, extract-duplicate-method, inline-immediately-returned-variable, merge-duplicate-blocks
        """递归转换defaultdict为普通dict"""
        if isinstance(data, defaultdict):
            # 转换defaultdict为普通dict
            result = {}
            for key, value in data.items():
                result[key] = self._convert_defaultdict_to_dict(value)
            return result
        elif isinstance(data, dict):
            # 递归处理普通dict
            result = {}
            for key, value in data.items():
                result[key] = self._convert_defaultdict_to_dict(value)
            return result
        else:
            # 其他类型直接返回
            return data

    # -- 以下为统计数据格式化方法 --

    @staticmethod
    def _format_total_stat(stats: dict[str, Any]) -> str:
        """
        格式化总统计数据
        """

        output = [
            f"总在线时间: {_format_online_time(stats.get(ONLINE_TIME, 0))}",
            f"总消息数: {stats.get(TOTAL_MSG_CNT, 0)}",
            f"总请求数: {stats.get(TOTAL_REQ_CNT, 0)}",
            f"总花费: {stats.get(TOTAL_COST, 0.0):.4f}¥",
            "",
        ]

        return "\n".join(output)

    @staticmethod
    def _format_model_classified_stat(stats: dict[str, Any]) -> str:
        """
        格式化按模型分类的统计数据
        """
        if stats.get(TOTAL_REQ_CNT, 0) <= 0:
            return ""
        data_fmt = "{:<32}  {:>10}  {:>12}  {:>12}  {:>12}  {:>9.4f}¥  {:>10}  {:>10}"

        output = [
            " 模型名称                          调用次数    输入Token     输出Token     Token总量     累计花费    平均耗时(秒)  标准差(秒)",
        ]
        for model_name, count in sorted(stats[REQ_CNT_BY_MODEL].items()):
            name = f"{model_name[:29]}..." if len(model_name) > 32 else model_name
            in_tokens = stats[IN_TOK_BY_MODEL][model_name]
            out_tokens = stats[OUT_TOK_BY_MODEL][model_name]
            tokens = stats[TOTAL_TOK_BY_MODEL][model_name]
            cost = stats[COST_BY_MODEL][model_name]
            avg_time_cost = stats[AVG_TIME_COST_BY_MODEL][model_name]
            std_time_cost = stats[STD_TIME_COST_BY_MODEL][model_name]
            output.append(
                data_fmt.format(name, count, in_tokens, out_tokens, tokens, cost, avg_time_cost, std_time_cost)
            )

        output.append("")
        return "\n".join(output)

    def _format_chat_stat(self, stats: dict[str, Any]) -> str:
        """
        格式化聊天统计数据
        """
        if stats.get(TOTAL_MSG_CNT, 0) <= 0:
            return ""
        output = ["聊天消息统计:", " 联系人/群组名称                  消息数量"]
        output.extend(
            f"{self.name_mapping.get(chat_id, (chat_id, 0))[0][:32]:<32}  {count:>10}"
            for chat_id, count in sorted(stats.get(MSG_CNT_BY_CHAT, {}).items())
        )
        output.append("")
        return "\n".join(output)

    async def _collect_chart_data(self, stat: dict[str, Any]) -> dict:
        """生成图表数据 (异步)"""
        now = datetime.now()
        chart_data: dict[str, Any] = {}

        time_ranges = [
            ("6h", 6, 10),
            ("12h", 12, 15),
            ("24h", 24, 15),
            ("48h", 48, 30),
        ]

        # 依次处理（数据量不大，避免复杂度；如需可改 gather）
        for range_key, hours, interval_minutes in time_ranges:
            chart_data[range_key] = await self._collect_interval_data(now, hours, interval_minutes)
        return chart_data

    async def _collect_interval_data(self, now: datetime, hours: int, interval_minutes: int) -> dict:
        start_time = now - timedelta(hours=hours)
        time_points: list[datetime] = []
        current_time = start_time
        while current_time <= now:
            time_points.append(current_time)
            current_time += timedelta(minutes=interval_minutes)

        total_cost_data = [0.0] * len(time_points)
        cost_by_model: dict[str, list[float]] = {}
        cost_by_module: dict[str, list[float]] = {}
        message_by_chat: dict[str, list[int]] = {}
        time_labels = [t.strftime("%H:%M") for t in time_points]
        interval_seconds = interval_minutes * 60

        # 🔧 内存优化：使用分批查询 LLMUsage
        llm_query_builder = (
            QueryBuilder(LLMUsage)
            .no_cache()
            .filter(timestamp__gte=start_time)
            .order_by("-timestamp")
        )
        
        async for batch in llm_query_builder.iter_batches(batch_size=STAT_BATCH_SIZE, as_dict=True):
            for record in batch:
                if not isinstance(record, dict) or not record.get("timestamp"):
                    continue
                record_time = record["timestamp"]
                if isinstance(record_time, str):
                    try:
                        record_time = datetime.fromisoformat(record_time)
                    except Exception:
                        continue
                time_diff = (record_time - start_time).total_seconds()
                idx = int(time_diff // interval_seconds)
                if 0 <= idx < len(time_points):
                    cost = record.get("cost") or 0.0
                    total_cost_data[idx] += cost
                    model_name = record.get("model_name") or "unknown"
                    if model_name not in cost_by_model:
                        cost_by_model[model_name] = [0.0] * len(time_points)
                    cost_by_model[model_name][idx] += cost
                    request_type = record.get("request_type") or "unknown"
                    module_name = request_type.split(".")[0] if "." in request_type else request_type
                    if module_name not in cost_by_module:
                        cost_by_module[module_name] = [0.0] * len(time_points)
                    cost_by_module[module_name][idx] += cost
            
            await asyncio.sleep(0)

        # 🔧 内存优化：使用分批查询 Messages
        msg_query_builder = (
            QueryBuilder(Messages)
            .no_cache()
            .filter(time__gte=start_time.timestamp())
            .order_by("-time")
        )
        
        async for batch in msg_query_builder.iter_batches(batch_size=STAT_BATCH_SIZE, as_dict=True):
            for msg in batch:
                if not isinstance(msg, dict) or not msg.get("time"):
                    continue
                msg_ts = msg["time"]
                time_diff = msg_ts - start_time.timestamp()
                idx = int(time_diff // interval_seconds)
                if 0 <= idx < len(time_points):
                    chat_id = None
                    if msg.get("chat_info_group_id"):
                        chat_id = f"g{msg['chat_info_group_id']}"
                    elif msg.get("user_id"):
                        chat_id = f"u{msg['user_id']}"

                    if chat_id:
                        chat_name = self.name_mapping.get(chat_id, (chat_id, 0))[0]
                        if chat_name not in message_by_chat:
                            message_by_chat[chat_name] = [0] * len(time_points)
                        message_by_chat[chat_name][idx] += 1
            
            await asyncio.sleep(0)

        return {
            "time_labels": time_labels,
            "total_cost_data": total_cost_data,
            "cost_by_model": cost_by_model,
            "cost_by_module": cost_by_module,
            "message_by_chat": message_by_chat,
        }
