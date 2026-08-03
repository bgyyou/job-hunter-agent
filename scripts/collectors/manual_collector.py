#!/usr/bin/env python3
"""手动 JD 收集器

使用方法：
1. 运行此脚本（首次需传 ``--user-id``）
2. 在打开的浏览器中正常浏览 JobsDB
3. 每找到一个感兴趣的职位，就回到终端按回车
4. 脚本会自动保存当前页面的职位信息
5. 完成后输入 'q' 退出
6. 退出后会问是否导入到 v2 库，确认即调 ``database.factory.get_db()``
   + ``services.jd_library_service.insert_user_jd`` +
   ``tools.jd_indexer.embed_and_store_jd_chunks`` 走 Flow B 可见的同一落库路径

M-v4-2 (P1-002b)：原实现走 v1 KnowledgeBase（多 DB 文件），与 v2 的
jobhunter_v2.db 不互通，导入后 Flow B 的 ``list_visible_jds`` 看不到。
与 P1-002 ``scripts/collectors/import_collected.py`` 改法一致：改走
``insert_user_jd`` + ``embed_and_store_jd_chunks``，分类从 v1 LLM
``classify_jd`` 换成 ``database.classifier.Classifier``（三层规则，
同步、无需 API key）。

user_id 走必填 CLI 参数而非 ``web_app.current_user_id()``：本脚本是
纯 CLI 入口，没有 Streamlit session。
"""
import argparse
import sys
from pathlib import Path

# 添加项目根目录到路径
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

import asyncio
import json
from datetime import datetime
from dotenv import load_dotenv
from loguru import logger

from tools.scraper.jobsdb_scraper import JobsDBScraper

# M-v4-2 P1-002b：v2 落库链路依赖放模块级别（便于 monkeypatch 测试），
# 脚本入口会 load_dotenv，故放 import 之后不影响 scraper 单独调用。
from database.classifier import Classifier
from database.factory import get_db
from services.jd_library_service import insert_user_jd
from tools.jd_indexer import embed_and_store_jd_chunks


async def main():
    """JD 收集器"""
    parser = argparse.ArgumentParser(description="手动 JD 收集器（写入 v2 jobhunter_v2.db）")
    parser.add_argument("--user-id", required=True,
                        help="导入 JD 的归属用户 id（必填 — 数据按用户隔离）")
    args = parser.parse_args()

    print("="*60)
    print(f"Job Hunter - JD 手动收集器（user_id={args.user_id}）")
    print("="*60)
    print()
    print("使用说明：")
    print("1. 浏览器会自动打开")
    print("2. 你可以正常浏览 JobsDB，搜索感兴趣的职位")
    print("3. 找到一个职位页面后，回到终端按回车")
    print("4. 脚本会自动保存当前职位")
    print("5. 继续找下一个，或输入 'q' 退出")
    print()

    # 使用持久化上下文
    from pathlib import Path
    user_data_dir = Path.home() / ".job_hunter" / "browser_data" / "jobsdb"

    scraper = JobsDBScraper(
        headless=False,
        user_data_dir=str(user_data_dir),
        browser_type="chromium"
    )

    # 保存目录
    output_dir = Path.home() / ".job_hunter" / "collected_jds"
    output_dir.mkdir(parents=True, exist_ok=True)

    collected_count = 0

    try:
        await scraper.start()

        # 先打开 JobsDB
        print("正在打开 JobsDB...")
        await scraper.navigate("https://hk.jobsdb.com")

        print()
        print("浏览器已打开！")
        print("开始浏览吧，找到好职位就回来按回车保存～")
        print()

        while True:
            print("-" * 60)
            print(f"已收集: {collected_count} 个职位")
            print()
            cmd = input("按回车保存当前页面，或输入 'q' 退出: ").strip().lower()

            if cmd == 'q':
                break

            try:
                # 获取当前页面信息
                print("正在保存...")

                # 获取页面内容
                page_url = scraper.page.url
                page_title = await scraper.page.title()
                page_html = await scraper.page.content()

                # 尝试提取职位信息
                try:
                    title_elem = await scraper.page.query_selector("h1")
                    title = await title_elem.inner_text() if title_elem else page_title
                except:
                    title = page_title

                # 获取页面全部文本
                page_text = await scraper.page.inner_text("body")

                # 保存
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                output_file = output_dir / f"jd_{timestamp}.json"

                jd_data = {
                    "title": title,
                    "url": page_url,
                    "raw_text": page_text,
                    "raw_html": page_html,
                    "collected_at": datetime.now().isoformat(),
                    "source": "jobsdb"
                }

                with open(output_file, 'w', encoding='utf-8') as f:
                    json.dump(jd_data, f, ensure_ascii=False, indent=2)

                collected_count += 1
                print(f"✅ 已保存! ({output_file.name})")
                print(f"   职位: {title[:50]}...")

            except Exception as e:
                logger.exception(f"保存失败: {e}")
                print(f"❌ 保存失败: {e}")

        print()
        print("="*60)
        print(f"收集完成！共收集 {collected_count} 个职位")
        print(f"保存在: {output_dir}")
        print("="*60)
        print()
        print("要导入这些 JD 到 v2 库吗？(y/n): ", end="")

        choice = input().strip().lower()
        if choice == 'y':
            import_to_v2(args.user_id, output_dir)

    except Exception as e:
        logger.exception(f"出错: {e}")
        return 1
    finally:
        try:
            await scraper.close()
        except:
            pass

    return 0


def import_to_v2(user_id: str, jd_dir: Path) -> int:
    """把 ``jd_dir`` 下 ``jd_*.json`` 导入到 v2 统一库。返回成功条数。

    M-v4-2 P1-002b: 与 ``scripts/collectors/import_collected.py`` 走同一条
    ``insert_user_jd`` + ``embed_and_store_jd_chunks`` 路径，分流入 v2。"""
    print()
    print(f"正在导入到 v2 库（user_id={user_id}）...")

    jd_files = sorted(jd_dir.glob("jd_*.json"))
    if not jd_files:
        print(f"  ❌ {jd_dir} 下没有 jd_*.json")
        return 0

    db = get_db()
    classifier = Classifier()
    imported_count = 0

    for jd_file in jd_files:
        try:
            with open(jd_file, "r", encoding="utf-8") as f:
                jd_data = json.load(f)

            title = jd_data.get("title") or "Untitled"
            raw_text = jd_data.get("raw_text") or ""
            print(f"分析: {title[:40]}...")

            jd_payload = {
                "url": jd_data.get("url", ""),
                "title": title,
                "company": jd_data.get("company", ""),
                "location": jd_data.get("location", ""),
                "raw_text": raw_text,
                "source": "manual_collector",
                "crawled_at": jd_data.get("collected_at"),
            }

            try:
                classification = classifier.classify(title=title, raw_text=raw_text)
                jd_payload["industry_tag"] = classification.get("industry_tag")
                jd_payload["function_tag"] = classification.get("function_tag")
                jd_payload["position_tag"] = classification.get("position_tag")
                jd_payload["auto_classified"] = 1
                tag = classification.get("position_tag") or "未分类"
            except Exception as exc:
                logger.warning(f"分类失败，按未分类入库: {exc}")
                tag = "未分类"

            jd_id = insert_user_jd(db, user_id, jd_payload)

            try:
                n_chunks = embed_and_store_jd_chunks(db, jd_id, raw_text, user_id=user_id)
            except Exception as exc:
                logger.warning(f"向量化失败 {jd_id}: {exc}")
                n_chunks = 0

            print(f"  ✅ 已入 v2 库: {tag} (ID: {jd_id[:8]}, chunks: {n_chunks})")
            imported_count += 1

            imported_dir = jd_dir / "imported"
            imported_dir.mkdir(exist_ok=True)
            jd_file.rename(imported_dir / jd_file.name)

        except Exception as e:
            logger.exception(f"导入 {jd_file.name} 失败: {e}")
            print(f"  ❌ 失败: {e}")

    print()
    print(f"✅ 导入完成！成功 {imported_count}/{len(jd_files)} 个 JD")
    print(f"可在 Flow B / JD 库中以 user_id={user_id} 查看这些 JD。")
    return imported_count


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
