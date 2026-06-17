#!/usr/bin/env python3
"""
JobHunter - JD爬虫
完全交互式参数输入
"""
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent
sys.path.insert(0, str(PROJECT_ROOT))

import asyncio
from jd_crawler_main import crawl_jobs, show_database


def print_welcome():
    print("\n" + "=" * 60)
    print("  JobHunter - JD爬虫")
    print("=" * 60)
    print("\n请选择操作:")
    print("  1. 自定义爬取")
    print("  2. 查看数据库")
    print("  3. 退出")


def get_keywords():
    """获取用户输入的关键词"""
    while True:
        print("\n请输入关键词（多个关键词用逗号分隔）:")
        input_str = input("> ").strip()
        if input_str:
            keywords = [k.strip() for k in input_str.split(",") if k.strip()]
            if keywords:
                return keywords
        print("❌ 关键词不能为空，请重新输入！")


def get_time_range():
    """获取时间范围选择"""
    valid_options = {"3", "7", "14", "30", "0"}
    while True:
        print("\n请选择时间范围:")
        print("  [3] 最近3天")
        print("  [7] 最近7天")
        print("  [14] 最近14天")
        print("  [30] 最近30天")
        print("  [0] 任意时间")
        choice = input("请选择: ").strip()
        if choice in valid_options:
            if choice == "0":
                return "any"
            return choice
        print(f"❌ 无效选择，请输入 3, 7, 14, 30 或 0！")


def get_max_jobs():
    """获取最大爬取数量"""
    while True:
        print("\n请输入最大爬取数量:")
        input_str = input("> ").strip()
        if input_str.isdigit() and int(input_str) > 0:
            return int(input_str)
        print("❌ 请输入有效的正整数！")


def get_human_speed():
    """获取人类速度倍数"""
    while True:
        print("\n请输入人类速度倍数（推荐0.3-2.0，默认0.5，按回车使用默认）:")
        input_str = input("> ").strip()
        if not input_str:
            return 0.5
        try:
            speed = float(input_str)
            if 0.1 <= speed <= 5.0:
                return speed
            print("⚠️  警告：建议范围是0.3-2.0，但仍将使用该值")
            return speed
        except ValueError:
            print("❌ 请输入有效的数字！")


def get_headless():
    """获取是否无头模式"""
    while True:
        print("\n是否使用无头模式（不显示浏览器）? (y/n，默认n):")
        input_str = input("> ").strip().lower()
        if not input_str or input_str == "n":
            return False
        if input_str == "y":
            return True
        print("❌ 请输入 y 或 n！")


def custom_crawl():
    """自定义爬取 - 完全交互式输入"""
    print("\n" + "=" * 60)
    print("⚙️  自定义爬取设置")
    print("=" * 60)

    keywords = get_keywords()
    time_range = get_time_range()
    max_jobs = get_max_jobs()
    human_speed = get_human_speed()
    headless = get_headless()

    print("\n" + "=" * 60)
    print("📋 确认设置:")
    print(f"  关键词: {', '.join(keywords)}")
    time_label = "任意时间" if time_range == "any" else f"{time_range}天"
    print(f"  时间范围: {time_label}")
    print(f"  最大数量: {max_jobs}")
    print(f"  人类速度: {human_speed}x")
    print(f"  无头模式: {'是' if headless else '否'}")
    print("=" * 60)

    confirm = input("\n确认开始爬取? (y/n): ").strip().lower()
    if confirm != "y":
        print("取消爬取。")
        return

    print("\n🚀 开始爬取...")
    asyncio.run(crawl_jobs(
        keywords=keywords,
        time_range=time_range,
        max_jobs=max_jobs,
        human_speed=human_speed,
        headless=headless,
    ))


def main():
    while True:
        print_welcome()
        choice = input("\n请选择: ").strip()

        if choice == "1":
            custom_crawl()
        elif choice == "2":
            show_database()
        elif choice == "3":
            print("\n👋 再见！\n")
            break
        else:
            print("\n❌ 无效选择，请重试")

        input("\n按回车继续...")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\n👋 程序停止\n")
