"""
机器人兴趣标签管理系统
基于人设生成兴趣标签，并使用embedding计算匹配度
"""
import orjson
import traceback
from typing import List, Dict, Optional, Any
from datetime import datetime
import numpy as np

from src.common.logger import get_logger
from src.common.data_models.bot_interest_data_model import (
    BotPersonalityInterests, BotInterestTag, InterestMatchResult
)

logger = get_logger("bot_interest_manager")


class BotInterestManager:
    """机器人兴趣标签管理器"""

    def __init__(self):
        self.current_interests: Optional[BotPersonalityInterests] = None
        self.embedding_cache: Dict[str, List[float]] = {}  # embedding缓存
        self._initialized = False

        # Embedding客户端配置
        self.embedding_request = None
        self.embedding_config = None
        self.embedding_dimension = 1024  # 默认BGE-M3 embedding维度

    @property
    def is_initialized(self) -> bool:
        """检查兴趣系统是否已初始化"""
        return self._initialized

    async def initialize(self, personality_description: str, personality_id: str = "default"):
        """初始化兴趣标签系统"""
        try:
            logger.info("=" * 60)
            logger.info("🚀 开始初始化机器人兴趣标签系统")
            logger.info(f"📋 人设ID: {personality_id}")
            logger.info(f"📝 人设描述长度: {len(personality_description)} 字符")
            logger.info("=" * 60)

            # 初始化embedding模型
            logger.info("🧠 正在初始化embedding模型...")
            await self._initialize_embedding_model()

            # 检查embedding客户端是否成功初始化
            if not self.embedding_request:
                raise RuntimeError("❌ Embedding客户端初始化失败，无法继续")

            # 生成或加载兴趣标签
            logger.info("🎯 正在生成或加载兴趣标签...")
            await self._load_or_generate_interests(personality_description, personality_id)

            self._initialized = True

            # 检查是否成功获取兴趣标签
            if self.current_interests and len(self.current_interests.get_active_tags()) > 0:
                active_tags_count = len(self.current_interests.get_active_tags())
                logger.info("=" * 60)
                logger.info("✅ 机器人兴趣标签系统初始化完成!")
                logger.info(f"📊 活跃兴趣标签数量: {active_tags_count}")
                logger.info(f"💾 Embedding缓存大小: {len(self.embedding_cache)}")
                logger.info("=" * 60)
            else:
                raise RuntimeError("❌ 未能成功生成或加载兴趣标签")

        except Exception as e:
            logger.error("=" * 60)
            logger.error(f"❌ 初始化机器人兴趣标签系统失败: {e}")
            logger.error("=" * 60)
            traceback.print_exc()
            raise  # 重新抛出异常，不允许降级初始化

    async def _initialize_embedding_model(self):
        """初始化embedding模型"""
        logger.info("🔧 正在配置embedding客户端...")

        # 使用项目配置的embedding模型
        from src.config.config import model_config
        from src.llm_models.utils_model import LLMRequest

        logger.debug("✅ 成功导入embedding相关模块")

        # 检查embedding配置是否存在
        if not hasattr(model_config.model_task_config, 'embedding'):
            raise RuntimeError("❌ 未找到embedding模型配置")

        logger.info("📋 找到embedding模型配置")
        self.embedding_config = model_config.model_task_config.embedding
        self.embedding_dimension = 1024  # BGE-M3的维度
        logger.info(f"📐 使用模型维度: {self.embedding_dimension}")

        # 创建LLMRequest实例用于embedding
        self.embedding_request = LLMRequest(model_set=self.embedding_config, request_type="interest_embedding")
        logger.info("✅ Embedding请求客户端初始化成功")
        logger.info(f"🔗 客户端类型: {type(self.embedding_request).__name__}")

        # 获取第一个embedding模型的ModelInfo
        if hasattr(self.embedding_config, 'model_list') and self.embedding_config.model_list:
            first_model_name = self.embedding_config.model_list[0]
            logger.info(f"🎯 使用embedding模型: {first_model_name}")
        else:
            logger.warning("⚠️  未找到embedding模型列表")

        logger.info("✅ Embedding模型初始化完成")

    async def _load_or_generate_interests(self, personality_description: str, personality_id: str):
        """加载或生成兴趣标签"""
        logger.info(f"📚 正在为 '{personality_id}' 加载或生成兴趣标签...")

        # 首先尝试从数据库加载
        logger.info("💾 尝试从数据库加载现有兴趣标签...")
        loaded_interests = await self._load_interests_from_database(personality_id)

        if loaded_interests:
            self.current_interests = loaded_interests
            active_count = len(loaded_interests.get_active_tags())
            logger.info(f"✅ 成功从数据库加载 {active_count} 个兴趣标签")
            logger.info(f"📅 最后更新时间: {loaded_interests.last_updated}")
            logger.info(f"🔄 版本号: {loaded_interests.version}")
        else:
            # 生成新的兴趣标签
            logger.info("🆕 数据库中未找到兴趣标签，开始生成新的...")
            logger.info("🤖 正在调用LLM生成个性化兴趣标签...")
            generated_interests = await self._generate_interests_from_personality(personality_description, personality_id)

            if generated_interests:
                self.current_interests = generated_interests
                active_count = len(generated_interests.get_active_tags())
                logger.info(f"✅ 成功生成 {active_count} 个兴趣标签")

                # 保存到数据库
                logger.info("💾 正在保存兴趣标签到数据库...")
                await self._save_interests_to_database(generated_interests)
            else:
                raise RuntimeError("❌ 兴趣标签生成失败")

    async def _generate_interests_from_personality(self, personality_description: str, personality_id: str) -> Optional[BotPersonalityInterests]:
        """根据人设生成兴趣标签"""
        try:
            logger.info("🎨 开始根据人设生成兴趣标签...")
            logger.info(f"📝 人设长度: {len(personality_description)} 字符")

            # 检查embedding客户端是否可用
            if not hasattr(self, 'embedding_request'):
                raise RuntimeError("❌ Embedding客户端未初始化，无法生成兴趣标签")

            # 构建提示词
            logger.info("📝 构建LLM提示词...")
            prompt = f"""
基于以下机器人人设描述，生成一套合适的兴趣标签：

人设描述：
{personality_description}

请生成一系列兴趣关键词标签，要求：
1. 标签应该符合人设特点和性格
2. 每个标签都有权重（0.1-1.0），表示对该兴趣的喜好程度
3. 生成15-25个不等的标签
4. 标签应该是具体的关键词，而不是抽象概念

请以JSON格式返回，格式如下：
{{
    "interests": [
        {{"name": "标签名", "weight": 0.8}},
        {{"name": "标签名", "weight": 0.6}},
        {{"name": "标签名", "weight": 0.9}}
    ]
}}

注意：
- 权重范围0.1-1.0，权重越高表示越感兴趣
- 标签要具体，如"编程"、"游戏"、"旅行"等
- 根据人设生成个性化的标签
"""

            # 调用LLM生成兴趣标签
            logger.info("🤖 正在调用LLM生成兴趣标签...")
            response = await self._call_llm_for_interest_generation(prompt)

            if not response:
                raise RuntimeError("❌ LLM未返回有效响应")

            logger.info("✅ LLM响应成功，开始解析兴趣标签...")
            interests_data = orjson.loads(response)

            bot_interests = BotPersonalityInterests(
                personality_id=personality_id,
                personality_description=personality_description
            )

            # 解析生成的兴趣标签
            interests_list = interests_data.get("interests", [])
            logger.info(f"📋 解析到 {len(interests_list)} 个兴趣标签")

            for i, tag_data in enumerate(interests_list):
                tag_name = tag_data.get("name", f"标签_{i}")
                weight = tag_data.get("weight", 0.5)

                tag = BotInterestTag(
                    tag_name=tag_name,
                    weight=weight
                )
                bot_interests.interest_tags.append(tag)

                logger.debug(f"   🏷️  {tag_name} (权重: {weight:.2f})")

            # 为所有标签生成embedding
            logger.info("🧠 开始为兴趣标签生成embedding向量...")
            await self._generate_embeddings_for_tags(bot_interests)

            logger.info("✅ 兴趣标签生成完成")
            return bot_interests

        except orjson.JSONDecodeError as e:
            logger.error(f"❌ 解析LLM响应JSON失败: {e}")
            raise
        except Exception as e:
            logger.error(f"❌ 根据人设生成兴趣标签失败: {e}")
            traceback.print_exc()
            raise

    
    async def _call_llm_for_interest_generation(self, prompt: str) -> Optional[str]:
        """调用LLM生成兴趣标签"""
        try:
            logger.info("🔧 配置LLM客户端...")

            # 使用llm_api来处理请求
            from src.plugin_system.apis import llm_api
            from src.config.config import model_config

            # 构建完整的提示词，明确要求只返回纯JSON
            full_prompt = f"""你是一个专业的机器人人设分析师，擅长根据人设描述生成合适的兴趣标签。

{prompt}

请确保返回格式为有效的JSON，不要包含任何额外的文本、解释或代码块标记。只返回JSON对象本身。"""
            
            # 使用replyer模型配置
            replyer_config = model_config.model_task_config.replyer
            
            # 调用LLM API
            logger.info("🚀 正在通过LLM API发送请求...")
            success, response, reasoning_content, model_name = await llm_api.generate_with_model(
                prompt=full_prompt,
                model_config=replyer_config,
                request_type="interest_generation",
                temperature=0.7,
                max_tokens=2000
            )

            if success and response:
                logger.info(f"✅ LLM响应成功，模型: {model_name}, 响应长度: {len(response)} 字符")
                logger.debug(f"📄 LLM响应内容: {response[:200]}..." if len(response) > 200 else f"📄 LLM响应内容: {response}")
                if reasoning_content:
                    logger.debug(f"🧠 推理内容: {reasoning_content[:100]}...")
                
                # 清理响应内容，移除可能的代码块标记
                cleaned_response = self._clean_llm_response(response)
                return cleaned_response
            else:
                logger.warning("⚠️ LLM返回空响应或调用失败")
                return None

        except Exception as e:
            logger.error(f"❌ 调用LLM生成兴趣标签失败: {e}")
            logger.error("🔍 错误详情:")
            traceback.print_exc()
            return None

    def _clean_llm_response(self, response: str) -> str:
        """清理LLM响应，移除代码块标记和其他非JSON内容"""
        import re
        
        # 移除 ```json 和 ``` 标记
        cleaned = re.sub(r'```json\s*', '', response)
        cleaned = re.sub(r'\s*```', '', cleaned)
        
        # 移除可能的多余空格和换行
        cleaned = cleaned.strip()
        
        # 尝试提取JSON对象（如果响应中有其他文本）
        json_match = re.search(r'\{.*\}', cleaned, re.DOTALL)
        if json_match:
            cleaned = json_match.group(0)
        
        logger.debug(f"🧹 清理后的响应: {cleaned[:200]}..." if len(cleaned) > 200 else f"🧹 清理后的响应: {cleaned}")
        return cleaned

    async def _generate_embeddings_for_tags(self, interests: BotPersonalityInterests):
        """为所有兴趣标签生成embedding"""
        if not hasattr(self, 'embedding_request'):
            raise RuntimeError("❌ Embedding客户端未初始化，无法生成embedding")

        total_tags = len(interests.interest_tags)
        logger.info(f"🧠 开始为 {total_tags} 个兴趣标签生成embedding向量...")

        cached_count = 0
        generated_count = 0
        failed_count = 0

        for i, tag in enumerate(interests.interest_tags, 1):
            if tag.tag_name in self.embedding_cache:
                # 使用缓存的embedding
                tag.embedding = self.embedding_cache[tag.tag_name]
                cached_count += 1
                logger.debug(f"   [{i}/{total_tags}] 🏷️  '{tag.tag_name}' - 使用缓存")
            else:
                # 生成新的embedding
                embedding_text = tag.tag_name

                logger.debug(f"   [{i}/{total_tags}] 🔄 正在为 '{tag.tag_name}' 生成embedding...")
                embedding = await self._get_embedding(embedding_text)

                if embedding:
                    tag.embedding = embedding
                    self.embedding_cache[tag.tag_name] = embedding
                    generated_count += 1
                    logger.debug(f"   ✅ '{tag.tag_name}' embedding生成成功")
                else:
                    failed_count += 1
                    logger.warning(f"   ❌ '{tag.tag_name}' embedding生成失败")

        if failed_count > 0:
            raise RuntimeError(f"❌ 有 {failed_count} 个兴趣标签embedding生成失败")

        interests.last_updated = datetime.now()
        logger.info("=" * 50)
        logger.info("✅ Embedding生成完成!")
        logger.info(f"📊 总标签数: {total_tags}")
        logger.info(f"💾 缓存命中: {cached_count}")
        logger.info(f"🆕 新生成: {generated_count}")
        logger.info(f"❌ 失败: {failed_count}")
        logger.info(f"🗃️  总缓存大小: {len(self.embedding_cache)}")
        logger.info("=" * 50)

    async def _get_embedding(self, text: str) -> List[float]:
        """获取文本的embedding向量"""
        if not hasattr(self, 'embedding_request'):
            raise RuntimeError("❌ Embedding请求客户端未初始化")

        # 检查缓存
        if text in self.embedding_cache:
            logger.debug(f"💾 使用缓存的embedding: '{text[:30]}...'")
            return self.embedding_cache[text]

        # 使用LLMRequest获取embedding
        logger.debug(f"🔄 正在获取embedding: '{text[:30]}...'")
        embedding, model_name = await self.embedding_request.get_embedding(text)

        if embedding and len(embedding) > 0:
            self.embedding_cache[text] = embedding
            logger.debug(f"✅ Embedding获取成功，维度: {len(embedding)}, 模型: {model_name}")
            return embedding
        else:
            raise RuntimeError(f"❌ 返回的embedding为空: {embedding}")

    async def _generate_message_embedding(self, message_text: str, keywords: List[str]) -> List[float]:
        """为消息生成embedding向量"""
        # 组合消息文本和关键词作为embedding输入
        if keywords:
            combined_text = f"{message_text} {' '.join(keywords)}"
        else:
            combined_text = message_text

        logger.debug(f"🔄 正在为消息生成embedding，输入长度: {len(combined_text)}")

        # 生成embedding
        embedding = await self._get_embedding(combined_text)
        logger.debug(f"✅ 消息embedding生成成功，维度: {len(embedding)}")
        return embedding

    async def _calculate_similarity_scores(self, result: InterestMatchResult, message_embedding: List[float], keywords: List[str]):
        """计算消息与兴趣标签的相似度分数"""
        try:
            if not self.current_interests:
                return

            active_tags = self.current_interests.get_active_tags()
            if not active_tags:
                return

            logger.debug(f"🔍 开始计算与 {len(active_tags)} 个兴趣标签的相似度")

            for tag in active_tags:
                if tag.embedding:
                    # 计算余弦相似度
                    similarity = self._calculate_cosine_similarity(message_embedding, tag.embedding)
                    weighted_score = similarity * tag.weight

                    # 设置相似度阈值为0.3
                    if similarity > 0.3:
                        result.add_match(tag.tag_name, weighted_score, keywords)
                        logger.debug(f"   🏷️  '{tag.tag_name}': 相似度={similarity:.3f}, 权重={tag.weight:.2f}, 加权分数={weighted_score:.3f}")

        except Exception as e:
            logger.error(f"❌ 计算相似度分数失败: {e}")

    async def calculate_interest_match(self, message_text: str, keywords: List[str] = None) -> InterestMatchResult:
        """计算消息与机器人兴趣的匹配度"""
        if not self.current_interests or not self._initialized:
            raise RuntimeError("❌ 兴趣标签系统未初始化")

        logger.info("🎯 开始计算兴趣匹配度...")
        logger.debug(f"💬 消息长度: {len(message_text)} 字符")
        if keywords:
            logger.debug(f"🏷️  关键词数量: {len(keywords)}")

        message_id = f"msg_{datetime.now().timestamp()}"
        result = InterestMatchResult(message_id=message_id)

        # 获取活跃的兴趣标签
        active_tags = self.current_interests.get_active_tags()
        if not active_tags:
            raise RuntimeError("❌ 没有活跃的兴趣标签")

        logger.info(f"📊 有 {len(active_tags)} 个活跃兴趣标签参与匹配")

        # 生成消息的embedding
        logger.debug("🔄 正在生成消息embedding...")
        message_embedding = await self._get_embedding(message_text)
        logger.debug(f"✅ 消息embedding生成成功，维度: {len(message_embedding)}")

        # 计算与每个兴趣标签的相似度
        match_count = 0
        high_similarity_count = 0
        medium_similarity_count = 0
        low_similarity_count = 0

        # 分级相似度阈值
        high_threshold = 0.5
        medium_threshold = 0.3
        low_threshold = 0.15

        logger.debug(f"🔍 使用分级相似度阈值: 高={high_threshold}, 中={medium_threshold}, 低={low_threshold}")

        for tag in active_tags:
            if tag.embedding:
                similarity = self._calculate_cosine_similarity(message_embedding, tag.embedding)

                # 基础加权分数
                weighted_score = similarity * tag.weight

                # 根据相似度等级应用不同的加成
                if similarity > high_threshold:
                    # 高相似度：强加成
                    enhanced_score = weighted_score * 1.5
                    match_count += 1
                    high_similarity_count += 1
                    result.add_match(tag.tag_name, enhanced_score, [tag.tag_name])
                    logger.debug(f"   🏷️  '{tag.tag_name}': 相似度={similarity:.3f}, 权重={tag.weight:.2f}, 基础分数={weighted_score:.3f}, 增强分数={enhanced_score:.3f} [高匹配]")

                elif similarity > medium_threshold:
                    # 中相似度：中等加成
                    enhanced_score = weighted_score * 1.2
                    match_count += 1
                    medium_similarity_count += 1
                    result.add_match(tag.tag_name, enhanced_score, [tag.tag_name])
                    logger.debug(f"   🏷️  '{tag.tag_name}': 相似度={similarity:.3f}, 权重={tag.weight:.2f}, 基础分数={weighted_score:.3f}, 增强分数={enhanced_score:.3f} [中匹配]")

                elif similarity > low_threshold:
                    # 低相似度：轻微加成
                    enhanced_score = weighted_score * 1.05
                    match_count += 1
                    low_similarity_count += 1
                    result.add_match(tag.tag_name, enhanced_score, [tag.tag_name])
                    logger.debug(f"   🏷️  '{tag.tag_name}': 相似度={similarity:.3f}, 权重={tag.weight:.2f}, 基础分数={weighted_score:.3f}, 增强分数={enhanced_score:.3f} [低匹配]")

        logger.info(f"📈 匹配统计: {match_count}/{len(active_tags)} 个标签超过阈值")
        logger.info(f"🔥 高相似度匹配(>{high_threshold}): {high_similarity_count} 个")
        logger.info(f"⚡ 中相似度匹配(>{medium_threshold}): {medium_similarity_count} 个")
        logger.info(f"🌊 低相似度匹配(>{low_threshold}): {low_similarity_count} 个")

        # 添加直接关键词匹配奖励
        keyword_bonus = self._calculate_keyword_match_bonus(keywords, result.matched_tags)
        logger.debug(f"🎯 关键词直接匹配奖励: {keyword_bonus}")

        # 应用关键词奖励到匹配分数
        for tag_name in result.matched_tags:
            if tag_name in keyword_bonus:
                original_score = result.match_scores[tag_name]
                bonus = keyword_bonus[tag_name]
                result.match_scores[tag_name] = original_score + bonus
                logger.debug(f"   🏷️  '{tag_name}': 原始分数={original_score:.3f}, 奖励={bonus:.3f}, 最终分数={result.match_scores[tag_name]:.3f}")

        # 计算总体分数
        result.calculate_overall_score()

        # 确定最佳匹配标签
        if result.matched_tags:
            top_tag_name = max(result.match_scores.items(), key=lambda x: x[1])[0]
            result.top_tag = top_tag_name
            logger.info(f"🏆 最佳匹配标签: '{top_tag_name}' (分数: {result.match_scores[top_tag_name]:.3f})")

        logger.info(f"📊 最终结果: 总分={result.overall_score:.3f}, 置信度={result.confidence:.3f}, 匹配标签数={len(result.matched_tags)}")
        return result

    
    def _calculate_keyword_match_bonus(self, keywords: List[str], matched_tags: List[str]) -> Dict[str, float]:
        """计算关键词直接匹配奖励"""
        if not keywords or not matched_tags:
            return {}

        bonus_dict = {}

        for tag_name in matched_tags:
            bonus = 0.0

            # 检查关键词与标签的直接匹配
            for keyword in keywords:
                keyword_lower = keyword.lower().strip()
                tag_name_lower = tag_name.lower()

                # 完全匹配
                if keyword_lower == tag_name_lower:
                    bonus += 0.3
                    logger.debug(f"   🎯 关键词完全匹配: '{keyword}' == '{tag_name}' (+0.3)")

                # 包含匹配
                elif keyword_lower in tag_name_lower or tag_name_lower in keyword_lower:
                    bonus += 0.15
                    logger.debug(f"   🎯 关键词包含匹配: '{keyword}' ⊃ '{tag_name}' (+0.15)")

                # 部分匹配（编辑距离）
                elif self._calculate_partial_match(keyword_lower, tag_name_lower):
                    bonus += 0.08
                    logger.debug(f"   🎯 关键词部分匹配: '{keyword}' ≈ '{tag_name}' (+0.08)")

            if bonus > 0:
                bonus_dict[tag_name] = min(bonus, 0.5)  # 最大奖励限制为0.5

        return bonus_dict

    def _calculate_partial_match(self, text1: str, text2: str) -> bool:
        """计算部分匹配（基于编辑距离）"""
        try:
            # 简单的编辑距离计算
            max_len = max(len(text1), len(text2))
            if max_len == 0:
                return False

            # 计算编辑距离
            distance = self._levenshtein_distance(text1, text2)

            # 如果编辑距离小于较短字符串长度的一半，认为是部分匹配
            min_len = min(len(text1), len(text2))
            return distance <= min_len // 2

        except Exception:
            return False

    def _levenshtein_distance(self, s1: str, s2: str) -> int:
        """计算莱文斯坦距离"""
        if len(s1) < len(s2):
            return self._levenshtein_distance(s2, s1)

        if len(s2) == 0:
            return len(s1)

        previous_row = range(len(s2) + 1)
        for i, c1 in enumerate(s1):
            current_row = [i + 1]
            for j, c2 in enumerate(s2):
                insertions = previous_row[j + 1] + 1
                deletions = current_row[j] + 1
                substitutions = previous_row[j] + (c1 != c2)
                current_row.append(min(insertions, deletions, substitutions))
            previous_row = current_row

        return previous_row[-1]

    def _calculate_cosine_similarity(self, vec1: List[float], vec2: List[float]) -> float:
        """计算余弦相似度"""
        try:
            vec1 = np.array(vec1)
            vec2 = np.array(vec2)

            dot_product = np.dot(vec1, vec2)
            norm1 = np.linalg.norm(vec1)
            norm2 = np.linalg.norm(vec2)

            if norm1 == 0 or norm2 == 0:
                return 0.0

            return dot_product / (norm1 * norm2)

        except Exception as e:
            logger.error(f"计算余弦相似度失败: {e}")
            return 0.0

    async def _load_interests_from_database(self, personality_id: str) -> Optional[BotPersonalityInterests]:
        """从数据库加载兴趣标签"""
        try:
            logger.info(f"💾 正在从数据库加载兴趣标签，personality_id: {personality_id}")

            # 导入SQLAlchemy相关模块
            from src.common.database.sqlalchemy_models import BotPersonalityInterests as DBBotPersonalityInterests
            from src.common.database.sqlalchemy_database_api import get_db_session
            import orjson

            with get_db_session() as session:
                # 查询最新的兴趣标签配置
                db_interests = session.query(DBBotPersonalityInterests).filter(
                    DBBotPersonalityInterests.personality_id == personality_id
                ).order_by(
                    DBBotPersonalityInterests.version.desc(),
                    DBBotPersonalityInterests.last_updated.desc()
                ).first()

                if db_interests:
                    logger.info(f"✅ 找到数据库中的兴趣标签配置，版本: {db_interests.version}")
                    logger.debug(f"📅 最后更新时间: {db_interests.last_updated}")
                    logger.debug(f"🧠 使用的embedding模型: {db_interests.embedding_model}")

                    # 解析JSON格式的兴趣标签
                    try:
                        tags_data = orjson.loads(db_interests.interest_tags)
                        logger.debug(f"🏷️  解析到 {len(tags_data)} 个兴趣标签")

                        # 创建BotPersonalityInterests对象
                        interests = BotPersonalityInterests(
                            personality_id=db_interests.personality_id,
                            personality_description=db_interests.personality_description,
                            embedding_model=db_interests.embedding_model,
                            version=db_interests.version,
                            last_updated=db_interests.last_updated
                        )

                        # 解析兴趣标签
                        for tag_data in tags_data:
                            tag = BotInterestTag(
                                tag_name=tag_data.get("tag_name", ""),
                                weight=tag_data.get("weight", 0.5),
                                created_at=datetime.fromisoformat(tag_data.get("created_at", datetime.now().isoformat())),
                                updated_at=datetime.fromisoformat(tag_data.get("updated_at", datetime.now().isoformat())),
                                is_active=tag_data.get("is_active", True),
                                embedding=tag_data.get("embedding")
                            )
                            interests.interest_tags.append(tag)

                        logger.info(f"✅ 成功从数据库加载 {len(interests.interest_tags)} 个兴趣标签")
                        return interests

                    except (orjson.JSONDecodeError, Exception) as e:
                        logger.error(f"❌ 解析兴趣标签JSON失败: {e}")
                        logger.debug(f"🔍 原始JSON数据: {db_interests.interest_tags[:200]}...")
                        return None
                else:
                    logger.info(f"ℹ️ 数据库中未找到personality_id为 '{personality_id}' 的兴趣标签配置")
                    return None

        except Exception as e:
            logger.error(f"❌ 从数据库加载兴趣标签失败: {e}")
            logger.error("🔍 错误详情:")
            traceback.print_exc()
            return None

    async def _save_interests_to_database(self, interests: BotPersonalityInterests):
        """保存兴趣标签到数据库"""
        try:
            logger.info("💾 正在保存兴趣标签到数据库...")
            logger.info(f"📋 personality_id: {interests.personality_id}")
            logger.info(f"🏷️  兴趣标签数量: {len(interests.interest_tags)}")
            logger.info(f"🔄 版本: {interests.version}")

            # 导入SQLAlchemy相关模块
            from src.common.database.sqlalchemy_models import BotPersonalityInterests as DBBotPersonalityInterests
            from src.common.database.sqlalchemy_database_api import get_db_session
            import orjson

            # 将兴趣标签转换为JSON格式
            tags_data = []
            for tag in interests.interest_tags:
                tag_dict = {
                    "tag_name": tag.tag_name,
                    "weight": tag.weight,
                    "created_at": tag.created_at.isoformat(),
                    "updated_at": tag.updated_at.isoformat(),
                    "is_active": tag.is_active,
                    "embedding": tag.embedding
                }
                tags_data.append(tag_dict)

            # 序列化为JSON
            json_data = orjson.dumps(tags_data)

            with get_db_session() as session:
                # 检查是否已存在相同personality_id的记录
                existing_record = session.query(DBBotPersonalityInterests).filter(
                    DBBotPersonalityInterests.personality_id == interests.personality_id
                ).first()

                if existing_record:
                    # 更新现有记录
                    logger.info("🔄 更新现有的兴趣标签配置")
                    existing_record.interest_tags = json_data
                    existing_record.personality_description = interests.personality_description
                    existing_record.embedding_model = interests.embedding_model
                    existing_record.version = interests.version
                    existing_record.last_updated = interests.last_updated

                    logger.info(f"✅ 成功更新兴趣标签配置，版本: {interests.version}")

                else:
                    # 创建新记录
                    logger.info("🆕 创建新的兴趣标签配置")
                    new_record = DBBotPersonalityInterests(
                        personality_id=interests.personality_id,
                        personality_description=interests.personality_description,
                        interest_tags=json_data,
                        embedding_model=interests.embedding_model,
                        version=interests.version,
                        last_updated=interests.last_updated
                    )
                    session.add(new_record)
                    logger.info(f"✅ 成功创建兴趣标签配置，版本: {interests.version}")

            logger.info("✅ 兴趣标签已成功保存到数据库")

            # 验证保存是否成功
            with get_db_session() as session:
                saved_record = session.query(DBBotPersonalityInterests).filter(
                    DBBotPersonalityInterests.personality_id == interests.personality_id
                ).first()
                session.commit()
                if saved_record:
                    logger.info(f"✅ 验证成功：数据库中存在personality_id为 {interests.personality_id} 的记录")
                    logger.info(f"   版本: {saved_record.version}")
                    logger.info(f"   最后更新: {saved_record.last_updated}")
                else:
                    logger.error(f"❌ 验证失败：数据库中未找到personality_id为 {interests.personality_id} 的记录")

        except Exception as e:
            logger.error(f"❌ 保存兴趣标签到数据库失败: {e}")
            logger.error("🔍 错误详情:")
            traceback.print_exc()

    def get_current_interests(self) -> Optional[BotPersonalityInterests]:
        """获取当前的兴趣标签配置"""
        return self.current_interests

    def get_interest_stats(self) -> Dict[str, Any]:
        """获取兴趣系统统计信息"""
        if not self.current_interests:
            return {"initialized": False}

        active_tags = self.current_interests.get_active_tags()

        return {
            "initialized": self._initialized,
            "total_tags": len(active_tags),
            "embedding_model": self.current_interests.embedding_model,
            "last_updated": self.current_interests.last_updated.isoformat(),
            "cache_size": len(self.embedding_cache)
        }

    async def update_interest_tags(self, new_personality_description: str = None):
        """更新兴趣标签"""
        try:
            if not self.current_interests:
                logger.warning("没有当前的兴趣标签配置，无法更新")
                return

            if new_personality_description:
                self.current_interests.personality_description = new_personality_description

            # 重新生成兴趣标签
            new_interests = await self._generate_interests_from_personality(
                self.current_interests.personality_description,
                self.current_interests.personality_id
            )

            if new_interests:
                new_interests.version = self.current_interests.version + 1
                self.current_interests = new_interests
                await self._save_interests_to_database(new_interests)
                logger.info(f"兴趣标签已更新，版本: {new_interests.version}")

        except Exception as e:
            logger.error(f"更新兴趣标签失败: {e}")
            traceback.print_exc()


# 创建全局实例（重新创建以包含新的属性）
bot_interest_manager = BotInterestManager()