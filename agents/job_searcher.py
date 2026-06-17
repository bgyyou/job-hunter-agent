# agents/job_searcher.py
"""
职位搜索 Agent - 真正的 Agent 实现

具备能力：
1. 规划能力 - 根据目标动态选择平台和策略
2. 工具调用 - 调用 Scraper 搜索
3. 记忆能力 - 记住搜索历史、登录状态
4. 错误恢复 - 平台失败时尝试其他平台
5. 反思能力 - 评估搜索结果质量
6. 成本意识 - 缓存机制
"""
from typing import Dict, Any, List, Optional
from datetime import datetime
import asyncio
from agents.base import BaseAgent, AgentPlan
from tools.scraper.boss_scraper import BossScraper
from models.job import JobPosting
from core.cache import Cache
from loguru import logger


class JobSearcher(BaseAgent):
    """
    职位搜索 Agent - 真正的 Agent 实现

    功能：
    1. 并行搜索多平台（效率）
    2. 登录状态管理（上下文感知）
    3. 结果去重（可靠性）
    4. 添加缓存（效率）
    5. 动态调整搜索策略（规划能力）
    """

    # 支持的爬虫
    SCRAPERS = {
        "boss": BossScraper,
        "jobsdb": None,  # 延迟导入
    }

    def __init__(self, cache: Optional[Cache] = None):
        """
        初始化职位搜索 Agent

        Args:
            cache: 缓存实例（可选）
        """
        super().__init__("job_searcher")
        self.cache = cache or Cache("data/job_search_cache")

        # 初始化爬虫实例
        self.scrapers: Dict[str, Any] = {}
        self._init_scrapers()

        # 登录状态（上下文感知）
        self.login_states: Dict[str, bool] = {}

        # 搜索历史（记忆能力）
        self.search_history: List[Dict[str, Any]] = []

        # 平台性能评估（反思能力）
        self.platform_performance: Dict[str, Dict[str, Any]] = {}

    def _init_scrapers(self):
        """初始化爬虫实例"""
        # 注意: JobsDBScraper 使用 Playwright，需要异步初始化
        # 推荐使用 job_hunter_cli.py 直接模式爬取 JobsDB

        for platform_name, scraper_class in self.SCRAPERS.items():
            if platform_name == "jobsdb":
                continue  # 跳过 JobsDB，推荐使用 CLI 直接模式
            if scraper_class is None:
                continue
            try:
                self.scrapers[platform_name] = scraper_class()
                self.logger.info(f"初始化爬虫: {platform_name}")
            except Exception as e:
                self.logger.error(f"初始化 {platform_name} 爬虫失败: {e}")

    # ==================== 规划能力 ====================

    async def plan(self, goal: str, input_data: Dict[str, Any]) -> AgentPlan:
        """
        规划搜索策略 - 规划能力

        根据目标、历史表现动态选择最佳策略
        """
        plan = AgentPlan(goal)

        keyword = input_data.get("keyword", "")
        location = input_data.get("location")
        platforms = input_data.get("platforms", list(self.SCRAPERS.keys()))

        # 分析历史表现
        platform_scores = self._analyze_platform_performance(keyword)

        # 根据表现排序平台
        sorted_platforms = sorted(
            platforms,
            key=lambda p: platform_scores.get(p, 0.5),
            reverse=True
        )

        self.logger.info(f"平台性能评估: {platform_scores}")
        self.logger.info(f"搜索顺序: {sorted_platforms}")

        # 检查缓存
        cache_key = self._get_cache_key(keyword, location, sorted_platforms, 1)
        cached = self.cache.get(cache_key)
        if cached:
            self.logger.info("使用缓存结果")
            plan.add_step("use_cache", "use_cache", {}, "使用缓存结果")
            return plan

        # 选择搜索策略
        search_strategy = self._determine_search_strategy(input_data, platform_scores)

        if search_strategy == "aggressive":
            # 激进策略：搜索更多平台和页面
            pages = min(input_data.get("pages", 1) * 2, 3)
            for platform in sorted_platforms:
                if platform in self.scrapers:
                    plan.add_step(
                        f"search_{platform}", "search_platform",
                        {"platform": platform, "keyword": keyword, "location": location, "pages": pages},
                        f"搜索 {platform} ({pages} 页)"
                    )
        elif search_strategy == "balanced":
            # 平衡策略：标准搜索
            pages = input_data.get("pages", 1)
            for platform in sorted_platforms:
                if platform in self.scrapers:
                    plan.add_step(
                        f"search_{platform}", "search_platform",
                        {"platform": platform, "keyword": keyword, "location": location, "pages": pages},
                        f"搜索 {platform}"
                    )
        else:
            # 保守策略：只搜索最佳平台
            best_platform = sorted_platforms[0] if sorted_platforms else "boss"
            pages = input_data.get("pages", 1)
            plan.add_step(
                f"search_{best_platform}", "search_platform",
                {"platform": best_platform, "keyword": keyword, "location": location, "pages": pages},
                f"搜索 {best_platform}"
            )

        # 后续步骤
        plan.add_step(
            "deduplicate", "deduplicate_jobs",
            {},
            "去重职位",
            depends_on=[i for i in range(len(plan.steps))]
        )
        plan.add_step(
            "evaluate_quality", "evaluate_search_quality",
            {},
            "评估搜索质量",
            depends_on=[len(plan.steps) - 1]
        )

        return plan

    def _analyze_platform_performance(self, keyword: str) -> Dict[str, float]:
        """分析平台历史表现 - 反思能力"""
        scores = {}

        for platform, history in self.platform_performance.items():
            if not history:
                scores[platform] = 0.5  # 默认分数
                continue

            # 计算成功率
            success_rate = history.get("success_rate", 0.5)

            # 计算平均结果数
            avg_results = history.get("avg_results", 10)

            # 计算平均速度
            avg_speed = history.get("avg_speed", 1.0)  # 结果/秒

            # 综合评分
            score = success_rate * 0.4 + \
                   min(avg_results / 20, 1) * 0.3 + \
                   min(avg_speed / 2, 1) * 0.3

            scores[platform] = score

        return scores

    def _determine_search_strategy(self, input_data: Dict[str, Any],
                               platform_scores: Dict[str, float]) -> str:
        """确定搜索策略"""
        keyword = input_data.get("keyword", "")

        # 新关键词：激进策略
        if not any(h.get("keyword") == keyword for h in self.search_history):
            return "aggressive"

        # 平台表现良好：平衡策略
        if any(score > 0.7 for score in platform_scores.values()):
            return "balanced"

        # 默认：保守策略
        return "conservative"

    def _get_goal(self, input_data: Dict[str, Any]) -> str:
        """获取目标"""
        keyword = input_data.get("keyword", "")
        location = input_data.get("location", "不限")
        return f"搜索 '{keyword}' 在 {location} 的职位"

    # ==================== 工具注册 ====================

    def _register_default_tools(self):
        """注册工具"""
        self.register_tool(
            "use_cache",
            "使用缓存结果",
            self._tool_use_cache
        )
        self.register_tool(
            "search_platform",
            "搜索单个平台",
            self._tool_search_platform
        )
        self.register_tool(
            "deduplicate_jobs",
            "职位去重",
            self._tool_deduplicate
        )
        self.register_tool(
            "evaluate_search_quality",
            "评估搜索质量",
            self._tool_evaluate_quality
        )

    async def _tool_use_cache(self) -> Dict[str, Any]:
        """工具：使用缓存"""
        keyword = self.state.get("current_keyword", "")
        location = self.state.get("current_location")
        platforms = self.state.get("current_platforms", [])

        cache_key = self._get_cache_key(keyword, location, platforms, 1)
        cached = self.cache.get(cache_key)

        if cached:
            self.logger.info(f"缓存命中: {len(cached.get('jobs', []))} 个职位")
            return {
                "jobs": cached.get("jobs", []),
                "total_count": cached.get("total_count", 0),
                "platforms_used": cached.get("platforms_used", []),
                "from_cache": True
            }

        return {"jobs": [], "total_count": 0}

    async def _tool_search_platform(
        self,
        platform: str,
        keyword: str,
        location: Optional[str],
        pages: int
    ) -> List[Dict[str, Any]]:
        """工具：搜索单个平台"""
        span = self.start_span(f"search_{platform}")

        try:
            scraper = self.scrapers.get(platform)
            if not scraper:
                self.logger.warning(f"平台不存在: {platform}")
                return []

            # 检查登录状态
            is_logged_in = await self._check_login_state(platform, scraper)
            if not is_logged_in:
                self.logger.warning(f"{platform} 未登录，尝试登录")
                try:
                    # 尝试登录（如果有登录方法）
                    if hasattr(scraper, "login"):
                        await scraper.login()
                        self.login_states[platform] = True
                except Exception as e:
                    self.logger.error(f"{platform} 登录失败: {e}")
                    return []

            all_jobs = []

            # 搜索多页
            for page in range(1, pages + 1):
                page_result = await self._search_single_page(
                    scraper=scraper,
                    platform=platform,
                    keyword=keyword,
                    location=location,
                    page=page
                )
                all_jobs.extend(page_result)

            self.logger.info(f"{platform} 搜索完成: {len(all_jobs)} 个职位")

            # 记录性能
            duration = (span.end_time - span.start_time).total_seconds() if span.end_time else 1.0
            self._update_platform_performance(
                platform,
                success=True,
                results_count=len(all_jobs),
                duration=duration
            )

            if span:
                self.end_span(True)

            return all_jobs

        except Exception as e:
            self.logger.error(f"{platform} 搜索失败: {e}")

            # 记录失败
            if span:
                self.end_span(False, str(e))
            self._update_platform_performance(platform, success=False, results_count=0, duration=1.0)

            return []

    async def _tool_deduplicate(self) -> List[Dict[str, Any]]:
        """工具：职位去重"""
        all_jobs = self.state.get("all_searched_jobs", [])

        seen = set()
        unique_jobs = []

        for job in all_jobs:
            # 使用 platform + job_id + title 作为唯一键
            job_key = f"{job.get('platform', '')}_{job.get('job_id', '')}_{job.get('title', '')}"
            if job_key and job_key not in seen:
                seen.add(job_key)
                unique_jobs.append(job)

        removed = len(all_jobs) - len(unique_jobs)
        if removed > 0:
            self.logger.info(f"去重：移除了 {removed} 个重复职位")

        return unique_jobs

    async def _tool_evaluate_quality(self) -> Dict[str, Any]:
        """工具：评估搜索质量 - 反思能力"""
        unique_jobs = self.state.get("unique_jobs", [])

        evaluation = {
            "total_count": len(unique_jobs),
            "quality_score": 0.5,
            "issues": []
        }

        if not unique_jobs:
            evaluation["quality_score"] = 0.0
            evaluation["issues"].append("未找到任何职位")
            return evaluation

        # 检查职位完整性
        complete_jobs = 0
        for job in unique_jobs:
            if job.get("title") and job.get("company") and job.get("url"):
                complete_jobs += 1

        completeness = complete_jobs / len(unique_jobs) if unique_jobs else 0
        evaluation["quality_score"] += completeness * 0.3

        # 检查是否有薪资信息
        jobs_with_salary = sum(1 for j in unique_jobs if j.get("salary_min"))
        salary_coverage = jobs_with_salary / len(unique_jobs) if unique_jobs else 0
        evaluation["quality_score"] += salary_coverage * 0.2

        # 检查结果数量是否合理
        if len(unique_jobs) < 5:
            evaluation["quality_score"] *= 0.7
            evaluation["issues"].append("搜索结果偏少，建议增加搜索范围或关键词")

        return evaluation

    # ==================== 反思能力 ====================

    def _update_platform_performance(
        self,
        platform: str,
        success: bool,
        results_count: int,
        duration: float
    ):
        """更新平台性能记录 - 反思能力"""
        if platform not in self.platform_performance:
            self.platform_performance[platform] = {
                "total_searches": 0,
                "success_count": 0,
                "total_results": 0,
                "total_duration": 0
            }

        perf = self.platform_performance[platform]
        perf["total_searches"] += 1

        if success:
            perf["success_count"] += 1
            perf["total_results"] += results_count
            perf["total_duration"] += duration

        # 计算平均指标
        if perf["total_searches"] > 0:
            perf["success_rate"] = perf["success_count"] / perf["total_searches"]
            perf["avg_results"] = perf["total_results"] / perf["total_searches"]
            perf["avg_speed"] = perf["avg_results"] / max(perf["total_duration"], 1.0)

        # 限制历史记录数量
        if perf["total_searches"] > 50:
            # 简单的滑动窗口衰减
            perf["total_searches"] = int(perf["total_searches"] * 0.9)
            perf["success_count"] = int(perf["success_count"] * 0.9)

    # ==================== 错误恢复 ====================

    async def _recover_from_failure(
        self,
        step: Dict,
        error: Exception,
        results: Dict
    ) -> Optional[Any]:
        """从失败中恢复"""
        step_name = step["name"]

        if step_name.startswith("search_"):
            platform = step_name.replace("search_", "")
            self.logger.warning(f"{platform} 搜索失败，尝试备用平台")

            # 尝试其他可用平台
            for other_platform in self.SCRAPERS.keys():
                if other_platform != platform and other_platform in self.scrapers:
                    self.logger.info(f"尝试备用平台: {other_platform}")
                    try:
                        keyword = self.state.get("current_keyword", "")
                        location = self.state.get("current_location")
                        pages = step["params"].get("pages", 1)

                        backup_result = await self._tool_search_platform(
                            platform=other_platform,
                            keyword=keyword,
                            location=location,
                            pages=pages
                        )
                        if backup_result:
                            return backup_result
                    except:
                        continue

            # 所有平台都失败，返回空列表
            return []

        return None

    # ==================== 核心执行 ====================

    async def execute(self, input_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        执行职位搜索

        Args:
            input_data: 输入数据，应包含：
                - keyword: 搜索关键词
                - location: 地点（可选）
                - platforms: 指定平台列表（可选）
                - pages: 搜索页数（可选）

        Returns:
            搜索结果
        """
        self.log_action("start_job_search", input_data)

        try:
            # 验证输入
            if not input_data.get("keyword"):
                raise ValueError("搜索关键词不能为空")

            keyword = input_data["keyword"]
            location = input_data.get("location")
            platforms = input_data.get("platforms", list(self.SCRAPERS.keys()))
            pages = input_data.get("pages", 1)

            # 检查平台是否支持
            platforms = [p for p in platforms if p in self.SCRAPERS]
            if not platforms:
                raise ValueError(f"没有可用的平台，支持的: {list(self.SCRAPERS.keys())}")

            # 保存到状态，供工具使用
            self.state["current_keyword"] = keyword
            self.state["current_location"] = location
            self.state["current_platforms"] = platforms

            # 检查缓存
            cache_key = self._get_cache_key(keyword, location, platforms, pages)
            cached = self.cache.get(cache_key)
            if cached:
                self.logger.info(f"使用缓存结果: {len(cached.get('jobs', []))} 个职位")
                self.set_reasoning(self._generate_reasoning(cached, from_cache=True))
                return {
                    "status": "success",
                    "jobs": cached["jobs"],
                    "total_count": cached["total_count"],
                    "platforms_used": cached["platforms_used"],
                    "reasoning": self.reasoning,
                    "from_cache": True
                }

            # 并行搜索
            all_jobs = await self._parallel_search(
                keyword=keyword,
                location=location,
                platforms=platforms,
                pages=pages
            )

            # 去重
            unique_jobs = self._deduplicate_jobs(all_jobs)

            # 转换为 JobPosting 模型
            job_postings = []
            for job_data in unique_jobs:
                try:
                    job_posting = self._convert_to_job_posting(job_data)
                    job_postings.append(job_posting)
                except Exception as e:
                    self.logger.warning(f"转换职位数据失败: {e}")
                    continue

            # 保存缓存
            result_data = {
                "jobs": [j.model_dump() for j in job_postings],
                "total_count": len(job_postings),
                "platforms_used": platforms
            }
            self.cache.set(cache_key, result_data, ttl=3600)

            # 更新搜索历史
            self.search_history.append({
                "keyword": keyword,
                "location": location,
                "timestamp": datetime.now().isoformat(),
                "result_count": len(job_postings)
            })
            if len(self.search_history) > 100:
                self.search_history = self.search_history[-100:]

            # 生成决策理由
            self.set_reasoning(self._generate_reasoning(result_data, from_cache=False))

            # 保存状态
            self.state["last_search"] = result_data
            self.save_state()

            self.log_action("search_complete", {
                "keyword": keyword,
                "count": len(job_postings),
                "platforms": platforms
            })

            return {
                "status": "success",
                "jobs": [j.model_dump() for j in job_postings],
                "total_count": len(job_postings),
                "platforms_used": platforms,
                "reasoning": self.reasoning,
                "from_cache": False
            }

        except Exception as e:
            self.logger.error(f"职位搜索失败: {e}")
            return {
                "status": "error",
                "error": str(e),
                "agent": self.name
            }

    async def _parallel_search(
        self,
        keyword: str,
        location: Optional[str],
        platforms: List[str],
        pages: int
    ) -> List[Dict[str, Any]]:
        """并行搜索多个平台"""
        self.state["all_searched_jobs"] = []
        self.state["unique_jobs"] = []

        # 创建搜索任务
        tasks = []
        for platform in platforms:
            if platform not in self.scrapers:
                continue

            task = self._tool_search_platform(
                platform=platform,
                keyword=keyword,
                location=location,
                pages=pages
            )
            tasks.append(task)

        # 并行执行
        results = await asyncio.gather(*tasks, return_exceptions=True)

        # 收集结果
        all_jobs = []
        for result in results:
            if isinstance(result, Exception):
                self.logger.error(f"搜索任务失败: {result}")
                continue
            if isinstance(result, list):
                all_jobs.extend(result)

        self.state["all_searched_jobs"] = all_jobs
        return all_jobs

    async def _search_single_page(
        self,
        scraper: Any,
        platform: str,
        keyword: str,
        location: Optional[str],
        page: int
    ) -> List[Dict[str, Any]]:
        """搜索单页职位"""
        try:
            self.logger.info(f"搜索 {platform} 第 {page} 页: {keyword}")

            jobs = await scraper.search_jobs(
                keyword=keyword,
                location=location,
                page=page
            )

            self.logger.info(f"{platform} 第 {page} 页返回 {len(jobs)} 个职位")
            return jobs

        except Exception as e:
            self.logger.error(f"{platform} 第 {page} 页搜索失败: {e}")
            return []

    def _deduplicate_jobs(self, jobs: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """职位去重"""
        seen = set()
        unique_jobs = []

        for job in jobs:
            job_key = f"{job.get('platform', '')}_{job.get('job_id', '')}"
            if job_key and job_key not in seen:
                seen.add(job_key)
                unique_jobs.append(job)

        removed = len(jobs) - len(unique_jobs)
        if removed > 0:
            self.logger.info(f"去重：移除了 {removed} 个重复职位")

        self.state["unique_jobs"] = unique_jobs
        return unique_jobs

    def _convert_to_job_posting(self, job_data: Dict[str, Any]) -> JobPosting:
        """转换为 JobPosting 模型"""
        return JobPosting(
            platform=job_data.get("platform", ""),
            job_id=job_data.get("job_id", ""),
            url=job_data.get("url", ""),
            title=job_data.get("title", ""),
            company=job_data.get("company", ""),
            location=job_data.get("location", ""),
            salary_min=job_data.get("salary_min"),
            salary_max=job_data.get("salary_max"),
            requirements=job_data.get("description", ""),
            skills_required=job_data.get("skills_required", [])
        )

    def _get_cache_key(
        self,
        keyword: str,
        location: Optional[str],
        platforms: List[str],
        pages: int
    ) -> str:
        """生成缓存键"""
        import hashlib
        data = f"{keyword}_{location}_{'-'.join(sorted(platforms))}_{pages}"
        return hashlib.md5(data.encode()).hexdigest()

    def _generate_reasoning(
        self,
        result_data: Dict[str, Any],
        from_cache: bool = False
    ) -> str:
        """生成决策理由"""
        reasoning_parts = []

        reasoning_parts.append(f"【搜索结果】共找到 {result_data['total_count']} 个职位")

        if from_cache:
            reasoning_parts.append("【来源】缓存结果（1小时内）")
        else:
            reasoning_parts.append("【来源】实时搜索")

        platforms = result_data.get("platforms_used", [])
        if platforms:
            reasoning_parts.append(f"【搜索平台】{', '.join(platforms)}")

        # 分析薪资分布
        jobs = result_data.get("jobs", [])
        if jobs:
            salaries = []
            for job in jobs:
                if job.get("salary_min"):
                    salaries.append(job["salary_min"])

            if salaries:
                avg_salary = sum(salaries) / len(salaries)
                reasoning_parts.append(f"【平均薪资】约 {avg_salary:.1f}k/月")

        reasoning_parts.append(f"【更新时间】{datetime.now().strftime('%Y-%m-%d %H:%M')}")

        return "\n".join(reasoning_parts)

    async def _check_login_state(self, platform: str, scraper: Any) -> bool:
        """检查登录状态"""
        if platform in self.login_states:
            return self.login_states[platform]

        if hasattr(scraper, "is_logged_in"):
            is_logged_in = await scraper.is_logged_in()
            self.login_states[platform] = is_logged_in
            return is_logged_in

        return False

    def update_login_state(self, platform: str, is_logged_in: bool):
        """更新登录状态"""
        self.login_states[platform] = is_logged_in
        self.logger.info(f"更新登录状态: {platform} = {'已登录' if is_logged_in else '未登录'}")

    def get_search_history(self, limit: int = 10) -> List[Dict[str, Any]]:
        """获取搜索历史"""
        return self.search_history[-limit:]

    def validate_input(self, input_data: Dict[str, Any]) -> bool:
        """验证输入"""
        if not super().validate_input(input_data):
            return False

        if not input_data.get("keyword"):
            self.logger.error("缺少搜索关键词")
            return False

        return True