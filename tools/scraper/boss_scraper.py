"""
BossScraper - Boss直聘爬虫

功能：
- 登录（二维码/手机号）
- 搜索职位
- 解析职位详情
"""

import asyncio
import json
import re
from typing import Dict, List, Optional, Any
from datetime import datetime
from bs4 import BeautifulSoup
from loguru import logger

from .base_scraper import BaseScraper


class BossScraper(BaseScraper):
    """
    Boss直聘爬虫

    支持职位搜索和详情解析
    """

    def __init__(self):
        """初始化 BossScraper"""
        super().__init__(
            platform_name="boss",
            base_url="https://www.zhipin.com",
        )

        # Boss直聘特有的 Headers
        self.session.headers.update({
            "Host": "www.zhipin.com",
            "Origin": "https://www.zhipin.com",
        })

    async def login(self, username: str, password: str) -> bool:
        """
        登录

        注意：Boss直聘通常需要手机验证码，这里提供基础框架
        实际使用建议手动登录后保存 Cookie

        Args:
            username: 用户名
            password: 密码

        Returns:
            是否登录成功
        """
        self.logger.info("尝试登录 Boss直聘")

        # 检查是否已经登录
        if await self.is_logged_in():
            self.logger.info("已处于登录状态")
            return True

        # 登录 URL
        login_url = f"{self.base_url}/web/user/"

        # 获取登录页面
        try:
            response = await self._request("GET", login_url)

            if "请登录" in response.text:
                self.logger.warning("需要手动登录，请使用浏览器登录后导入 Cookie")
                return False

            # 尝试登录（实际需要验证码）
            login_data = {
                "username": username,
                "password": password,
                "region": "gz",
                "code": "",  # 验证码
            }

            response = await self._request("POST", login_url, json=login_data)

            result = response.json()

            if result.get("code") == 0:
                self.logger.info("登录成功")
                return True
            else:
                self.logger.error(f"登录失败: {result.get('message', '未知错误')}")
                return False

        except Exception as e:
            self.logger.exception(f"登录异常: {e}")
            return False

    async def is_logged_in(self) -> bool:
        """
        检查是否已登录

        Returns:
            是否已登录
        """
        try:
            # 检查关键 Cookie 是否存在
            has_token = self.cookie_manager.has_cookie("wt2")
            has_sid = self.cookie_manager.has_cookie("uToken")

            if has_token and has_sid:
                # 验证 Cookie 是否有效
                test_url = f"{self.base_url}/web/user/"
                response = await self._request("GET", test_url)

                # 如果返回的是用户信息而不是登录页，说明已登录
                is_valid = "请登录" not in response.text and "我的" in response.text

                return is_valid

            return False

        except Exception as e:
            self.logger.error(f"检查登录状态失败: {e}")
            return False

    async def search_jobs(
        self,
        keyword: str,
        location: Optional[str] = None,
        page: int = 1,
        experience: Optional[str] = None,
        education: Optional[str] = None,
        salary_range: Optional[str] = None,
        **kwargs
    ) -> List[Dict[str, Any]]:
        """
        搜索职位

        Args:
            keyword: 搜索关键词
            location: 地点（如 "深圳"、"北京"）
            page: 页码
            experience: 工作经验（如 "3年"、"3-5年"）
            education: 学历要求（如 "本科"、"硕士"）
            salary_range: 薪资范围（如 "10k-20k"）
            **kwargs: 其他参数

        Returns:
            职位列表
        """
        self.logger.info(f"搜索职位: {keyword}, 地点: {location}, 页码: {page}")

        # Boss直聘的搜索 URL
        search_url = f"{self.base_url}/web/geek/job"

        # 地点编码映射
        location_map = {
            "深圳": "101280600",
            "广州": "101280100",
            "北京": "101010100",
            "上海": "101020100",
            "杭州": "101210100",
            "成都": "101270100",
            "武汉": "101200100",
            "西安": "101110100",
        }

        location_code = location_map.get(location, "")

        # 构建参数
        params = {
            "query": keyword,
            "city": location_code,
            "page": page,
        }

        # 可选参数
        if experience:
            params["experience"] = experience
        if education:
            params["education"] = education
        if salary_range:
            params["salary"] = salary_range

        try:
            response = await self._request("GET", search_url, params=params)

            # 解析 HTML
            soup = self._parse_html(response.text)

            # 提取职位卡片
            job_cards = soup.select(".job-card-wrapper")

            if not job_cards:
                # 检查是否是 JSON 响应
                json_match = re.search(r'\{[\s\S]*\}', response.text)
                if json_match:
                    json_data = json.loads(json_match.group())
                    return self._parse_json_jobs(json_data)

                self.logger.warning("未找到职位，可能需要登录或没有结果")
                return []

            # 解析职位卡片
            jobs = []
            for card in job_cards:
                job = self._parse_job_card(card)
                if job:
                    jobs.append(job)

            # 去重
            jobs = self._deduplicate_jobs(jobs)

            self.logger.info(f"找到 {len(jobs)} 个职位（第 {page} 页）")
            return jobs

        except Exception as e:
            self.logger.exception(f"搜索职位失败: {e}")
            return []

    def _parse_job_card(self, card: BeautifulSoup) -> Optional[Dict[str, Any]]:
        """
        解析职位卡片

        Args:
            card: BeautifulSoup 元素

        Returns:
            职位字典
        """
        try:
            # 职位标题和链接
            title_elem = card.select_one(".job-name")
            if not title_elem:
                return None

            title = title_elem.get_text(strip=True)
            link_elem = title_elem.find_parent("a")
            job_url = link_elem.get("href", "") if link_elem else ""
            if job_url:
                job_url = f"{self.base_url}{job_url}"

            # 职位 ID
            job_id_match = re.search(r'/(\d+)\.html', job_url)
            job_id = job_id_match.group(1) if job_id_match else ""

            # 公司信息
            company_elem = card.select_one(".company-name")
            company = company_elem.get_text(strip=True) if company_elem else ""

            # 薪资
            salary_elem = card.select_one(".salary")
            salary = salary_elem.get_text(strip=True) if salary_elem else "面议"

            # 解析薪资范围
            salary_min, salary_max = self._parse_salary(salary)

            # 地点
            location_elem = card.select_one(".job-area")
            location = location_elem.get_text(strip=True) if location_elem else ""

            # 经验和学历
            tags = card.select(".tag-list li")
            experience = ""
            education = ""
            if len(tags) >= 1:
                experience = tags[0].get_text(strip=True)
            if len(tags) >= 2:
                education = tags[1].get_text(strip=True)

            # 技能标签
            skill_tags = card.select(".job-card-footer .tags span")
            skills = [tag.get_text(strip=True) for tag in skill_tags]

            # 职位描述预览
            desc_elem = card.select_one(".job-card-footer .info-desc")
            description = desc_elem.get_text(strip=True) if desc_elem else ""

            # 发布时间
            time_elem = card.select_one(".job-pub-time")
            pub_time = time_elem.get_text(strip=True) if time_elem else ""

            return {
                "platform": "boss",
                "job_id": job_id,
                "url": job_url,
                "title": title,
                "company": company,
                "location": location,
                "salary_min": salary_min,
                "salary_max": salary_max,
                "salary_text": salary,
                "experience": experience,
                "education": education,
                "skills_required": skills,
                "description": description,
                "pub_time": pub_time,
                "scraped_at": datetime.now().isoformat(),
            }

        except Exception as e:
            self.logger.debug(f"解析职位卡片失败: {e}")
            return None

    def _parse_salary(self, salary_text: str) -> tuple[Optional[int], Optional[int]]:
        """
        解析薪资字符串

        Args:
            salary_text: 薪资文本（如 "10-20K"、"10-20K·14薪"）

        Returns:
            (最低薪资, 最高薪资)，单位：k
        """
        # 移除 "薪"、空格等
        clean_text = re.sub(r'[薪\s]', '', salary_text)

        # 匹配 "10-20K" 格式
        match = re.search(r'(\d+)-(\d+)K?', clean_text, re.IGNORECASE)
        if match:
            min_sal = int(match.group(1))
            max_sal = int(match.group(2))
            return (min_sal, max_sal)

        # 匹配 "20K以上" 格式
        match = re.search(r'(\d+)K以上', clean_text, re.IGNORECASE)
        if match:
            min_sal = int(match.group(1))
            return (min_sal, None)

        # 匹配 "20K以下" 格式
        match = re.search(r'(\d+)K以下', clean_text, re.IGNORECASE)
        if match:
            max_sal = int(match.group(1))
            return (None, max_sal)

        # 匹配 "20K" 格式
        match = re.search(r'(\d+)K', clean_text, re.IGNORECASE)
        if match:
            sal = int(match.group(1))
            return (sal, sal)

        return (None, None)

    def _parse_json_jobs(self, json_data: Dict) -> List[Dict[str, Any]]:
        """
        解析 JSON 格式的职位列表

        Args:
            json_data: JSON 数据

        Returns:
            职位列表
        """
        jobs = []

        # Boss直聘的 JSON 格式可能在不同的字段中
        if "data" in json_data and "jobList" in json_data["data"]:
            job_list = json_data["data"]["jobList"]
        elif "zpData" in json_data and "jobList" in json_data["zpData"]:
            job_list = json_data["zpData"]["jobList"]
        else:
            return jobs

        for job in job_list:
            try:
                jobs.append({
                    "platform": "boss",
                    "job_id": str(job.get("encryptJobId", "")),
                    "url": f"{self.base_url}/job_detail/{job.get('encryptJobId', '')}",
                    "title": job.get("jobName", ""),
                    "company": job.get("brandName", ""),
                    "location": job.get("cityName", "") + job.get("areaDistrict", ""),
                    "salary_min": None,
                    "salary_max": None,
                    "salary_text": job.get("salaryDesc", ""),
                    "experience": job.get("jobExperience", ""),
                    "education": job.get("jobDegree", ""),
                    "skills_required": job.get("skills", []),
                    "description": job.get("jobDescription", ""),
                    "pub_time": job.get("lastModifyTime", ""),
                    "scraped_at": datetime.now().isoformat(),
                })
            except Exception as e:
                self.logger.debug(f"解析 JSON 职位失败: {e}")
                continue

        return jobs

    async def parse_job(self, job_url: str) -> Dict[str, Any]:
        """
        解析职位详情

        Args:
            job_url: 职位 URL

        Returns:
            职位详情字典
        """
        self.logger.info(f"解析职位详情: {job_url}")

        try:
            response = await self._request("GET", job_url)

            soup = self._parse_html(response.text)

            # 检查是否登录
            if "请登录" in response.text or "login" in response.url:
                self.logger.warning("需要登录才能查看职位详情")
                return {}

            # 解析职位详情
            job_detail = {
                "url": job_url,
                "title": "",
                "company": "",
                "location": "",
                "salary_text": "",
                "experience": "",
                "education": "",
                "description": "",
                "skills_required": [],
                "company_info": {},
            }

            # 职位标题
            title_elem = soup.select_one(".job-primary .job-name")
            if title_elem:
                job_detail["title"] = title_elem.get_text(strip=True)

            # 公司信息
            company_elem = soup.select_one(".job-primary .company-name")
            if company_elem:
                job_detail["company"] = company_elem.get_text(strip=True)

            # 薪资
            salary_elem = soup.select_one(".job-primary .salary")
            if salary_elem:
                job_detail["salary_text"] = salary_elem.get_text(strip=True)
                job_detail["salary_min"], job_detail["salary_max"] = self._parse_salary(
                    job_detail["salary_text"]
                )

            # 位置
            location_elem = soup.select_one(".job-primary .job-location")
            if location_elem:
                job_detail["location"] = location_elem.get_text(strip=True)

            # 经验和学历
            info_items = soup.select(".job-primary .job-detail .job-primary-detail")
            for item in info_items:
                text = item.get_text(strip=True)
                if "经验" in text:
                    job_detail["experience"] = text
                elif "学历" in text:
                    job_detail["education"] = text

            # 职位描述
            desc_elem = soup.select_one(".job-sec-text")
            if desc_elem:
                job_detail["description"] = desc_elem.get_text(strip=True)

            # 技能要求
            skill_items = soup.select(".job-sec-item-list li")
            job_detail["skills_required"] = [
                item.get_text(strip=True) for item in skill_items
            ]

            # 公司详细信息
            company_info_elem = soup.select_one(".job-company")
            if company_info_elem:
                job_detail["company_info"] = {
                    "industry": company_info_elem.select_one(".company-industry").get_text(strip=True)
                    if company_info_elem.select_one(".company-industry") else "",
                    "scale": company_info_elem.select_one(".company-scale").get_text(strip=True)
                    if company_info_elem.select_one(".company-scale") else "",
                    "homepage": "",
                }

                # 公司主页
                link_elem = company_info_elem.select_one(".company-href")
                if link_elem:
                    href = link_elem.get("href", "")
                    if href:
                        job_detail["company_info"]["homepage"] = href

            self.logger.info(f"成功解析职位: {job_detail['title']}")
            return job_detail

        except Exception as e:
            self.logger.exception(f"解析职位详情失败: {e}")
            return {}

    async def get_user_profile(self) -> Dict[str, Any]:
        """
        获取用户信息

        Returns:
            用户信息字典
        """
        self.logger.info("获取用户信息")

        try:
            profile_url = f"{self.base_url}/web/user/"
            response = await self._request("GET", profile_url)

            soup = self._parse_html(response.text)

            user_info = {
                "name": "",
                "resume_status": "",
                "view_count": 0,
            }

            # 用户姓名
            name_elem = soup.select_one(".user-name")
            if name_elem:
                user_info["name"] = name_elem.get_text(strip=True)

            # 简历状态
            status_elem = soup.select_one(".resume-status")
            if status_elem:
                user_info["resume_status"] = status_elem.get_text(strip=True)

            # 浏览量
            view_elem = soup.select_one(".view-count")
            if view_elem:
                view_text = view_elem.get_text(strip=True)
                match = re.search(r'(\d+)', view_text)
                if match:
                    user_info["view_count"] = int(match.group(1))

            return user_info

        except Exception as e:
            self.logger.exception(f"获取用户信息失败: {e}")
            return {}

    async def get_recommendations(self, limit: int = 20) -> List[Dict[str, Any]]:
        """
        获取推荐职位

        Args:
            limit: 数量限制

        Returns:
            职位列表
        """
        self.logger.info(f"获取推荐职位，限制: {limit}")

        try:
            recommend_url = f"{self.base_url}/web/geek/recommend"
            response = await self._request("GET", recommend_url)

            soup = self._parse_html(response.text)

            # 解析职位卡片
            job_cards = soup.select(".job-card-wrapper")

            jobs = []
            for card in job_cards[:limit]:
                job = self._parse_job_card(card)
                if job:
                    jobs.append(job)

            self.logger.info(f"获取到 {len(jobs)} 个推荐职位")
            return jobs

        except Exception as e:
            self.logger.exception(f"获取推荐职位失败: {e}")
            return []

    def __repr__(self) -> str:
        return f"BossScraper(platform=boss)"