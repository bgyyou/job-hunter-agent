# JobHunter JD爬虫使用说明

## 快速开始

### 方式一：一键启动（推荐）

```bash
python start_crawler.py
```

然后按提示选择：
- **选项1** - 快速爬取（AI相关职位，7天内，20个）
- **选项2** - 自定义爬取
- **选项3** - 查看数据库

### 方式二：命令行直接调用

```bash
# 使用默认设置
python jd_crawler_main.py

# 指定关键词
python jd_crawler_main.py --keywords "AI PM" "AI Engineer"

# 指定时间范围和数量
python jd_crawler_main.py --time 3 --max-jobs 30

# 仅查看数据库
python jd_crawler_main.py --show

# 无头模式（不显示浏览器）
python jd_crawler_main.py --headless
```

## 文件说明

| 文件 | 说明 |
|------|------|
| `start_crawler.py` | 交互式一键启动脚本 |
| `jd_crawler_main.py` | 主爬虫程序，支持命令行参数 |
| `tools/scraper/jobsdb_scraper.py` | JobsDB爬虫核心 |
| `tools/scraper/human_playwright_scraper.py` | 类人行为浏览器 |

## 数据库

- 默认位置：`~/.job_hunter/crawler.db`
- 包含字段：url, title, company, raw_text, search_keyword, days_old, crawled_at

## 命令行参数说明

```
--keywords KEYWORD1 KEYWORD2...  搜索关键词列表
--time {3,7,14,30,any}           发布时间范围（默认7天）
--max-jobs N                     最大爬取数量（默认50）
--speed FLOAT                    人类速度倍数（默认0.5）
--headless                       无头模式（不显示浏览器）
--show                           仅显示数据库内容
```

## 使用示例

### 示例1：快速爬取AI产品经理职位

```bash
python start_crawler.py
# 选择 1
```

### 示例2：自定义爬取

```bash
python jd_crawler_main.py \
  --keywords "AI Product Manager" "Data Scientist" \
  --time 7 \
  --max-jobs 30 \
  --speed 0.5
```

### 示例3：查看已爬取的职位

```bash
python jd_crawler_main.py --show
```

## 注意事项

1. 首次使用建议不用无头模式，观察浏览器行为
2. 速度建议设置0.3-0.5之间，太快可能触发反爬
3. 数据库自动去重，同一URL不会重复爬取
4. 支持Microsoft Edge浏览器（已默认配置）
