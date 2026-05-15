# Amazon Category & Product Scraper (高性能亚马逊品类/商品爬虫)

这是一个基于 `DrissionPage` 开发的高性能亚马逊爬虫系统。它支持全自动递归抓取品类树、多线程并发抓取商品详情，并提供 MySQL 数据库实时存储与 Excel 自动备份双重保障。

## 🚀 核心功能

1.  **品类拓荒 (`GET_CATEGORIES.py`)**：
    *   自动从亚马逊 Best Sellers 首页开始，递归挖掘所有子品类链接。
    *   支持层级标记（Level 1, 2, 3...），构建完整的抓取任务池。
2.  **增量抓取任务队列**：
    *   基于 MySQL 的 `amazon_tasks` 表管理任务。
    *   自动识别未爬取的品类 (`status=0`)，支持断点续爬。
3.  **多线程并发抓取 (`AMAZON.py`)**：
    *   支持多线程并行爬取，显著提升采集速度。
    *   **实时入库**：每抓取一个商品及其评论，立即写入 MySQL。
    *   **Excel 备份**：每个品类处理完毕后，自动生成数据备份文件。
4.  **高鲁棒性解析**：
    *   精准提取 ASIN、标题、规格尺寸、原价/现价、折扣、五点描述、SKU 信息等。
    *   **规格优化**：通过关键字匹配（Dimensions）解决传统爬虫易误抓“手机型号”的问题。
    *   **评论提取**：自动抓取商品首页的所有详细评论。
5.  **反爬对抗**：
    *   自动处理滚动加载（Lazy Load）。
    *   内置随机请求延迟与 UA 伪装。
    *   支持浏览器实例的线程安全隔离。

## 📂 文件结构

*   `AMAZON.py`: **主爬虫程序**，负责多线程执行商品详情页的抓取。
*   `GET_CATEGORIES.py`: **品类挖掘程序**，用于初始化和扩展任务池。
*   `db_config.py`: **数据库配置**，设置 MySQL 连接信息及表名。
*   `db_setup.py`: **表结构初始化**，自动创建所需的数据库表和索引。
*   `excel/`: 存放自动生成的商品与评论备份文件。

## 🛠️ 安装与配置

### 1. 环境依赖
确保已安装 Python 3.8+。在项目目录下运行：
```bash
pip install -r requirements.txt
```

### 2. 数据库配置
修改 `db_config.py`，填写您的 MySQL 连接信息：
```python
DB_HOST = '127.0.0.1'
DB_USER = 'root'
DB_PASS = '您的密码'
DB_NAME = 'amazon_crawl'
```

## 📖 运行说明

建议按以下顺序操作：

### 第一步：挖掘品类链接
运行 `GET_CATEGORIES.py`。它会扫描亚马逊导航树，并将发现的品类链接存入任务表。
```bash
python GET_CATEGORIES.py
```

### 第二步：开始正式抓取
运行 `AMAZON.py`。它会从任务池读取 `status=0` 的品类，并使用多线程开始抓取商品数据。
```bash
python -u AMAZON.py
```

## ⚙️ 进阶配置 (`AMAZON.py`)

您可以在 `AMAZON.py` 的顶部配置区调整性能参数：
*   `THREAD_COUNT`: 并发线程数（推荐 2-5，不建议超过 10 以防触发封禁）。
*   `TEST_LIMIT`: 测试模式开关（设为 0 表示全量抓取，设为 N 表示每个品类只抓前 N 个商品）。

## ⚠️ 注意事项
*   **浏览器路径**：请确保 `db_config.py` 或脚本内的 `browser_path` 指向您电脑上正确的 Edge 或 Chrome 可执行文件路径。
*   **反爬虫**：如遇到高频验证码，请适当降低 `THREAD_COUNT` 或增大随机延迟。
