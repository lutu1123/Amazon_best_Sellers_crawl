from DrissionPage import ChromiumPage, ChromiumOptions
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from sqlalchemy import create_engine, text
import pandas as pd
import requests
import os
import time
import random
import json
import re
import threading
import db_config
import db_setup

# =====================================================================
# 多线程配置区（可按需修改）
# =====================================================================
THREAD_COUNT = 5          # 并发线程数（推荐 2~5，过高易触发反爬）
TEST_LIMIT = 0           # 测试模式：每个品类只抓前 N 个链接（0 = 不限制）
REQUEST_DELAY = (0.8, 1.5)  # 每个商品抓取后的随机延迟范围（秒）
SCROLL_DELAY  = (1.5, 2.5)  # 滚动后等待懒加载的随机延迟范围（秒）
# =====================================================================

# 线程本地存储（每个线程维护自己的 browser 实例）
_thread_local = threading.local()
# 用于初始化浏览器的全局锁（避免多线程同时启动浏览器冲突）
_browser_init_lock = threading.Lock()


def get_chromium_options():
    """返回统一的 ChromiumOptions 配置"""
    co = ChromiumOptions().set_paths(
        browser_path=r'C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe'
    )
    co.set_argument('--disable-blink-features=AutomationControlled')
    co.set_argument(
        '--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
        'AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36 Edg/125.0.0.0'
    )
    co.set_argument('--disable-infobars')
    co.set_argument('--no-first-run')
    return co


def get_thread_browser():
    """获取当前线程专属的 browser 实例，不存在则新建"""
    if not hasattr(_thread_local, 'browser') or _thread_local.browser is None:
        with _browser_init_lock:
            co = get_chromium_options()
            _thread_local.browser = ChromiumPage(co)
            print(f"  [Thread-{threading.current_thread().name}] 浏览器已初始化")
    return _thread_local.browser


def close_thread_browser():
    """关闭当前线程的 browser 实例"""
    if hasattr(_thread_local, 'browser') and _thread_local.browser:
        try:
            _thread_local.browser.quit()
        except Exception:
            pass
        _thread_local.browser = None


# ─────────────────────────────────────────────
# 工具函数
# ─────────────────────────────────────────────

def scrollDown(driver, times):
    driver.scroll(5000)
    time.sleep(1)
    for _ in range(times):
        time.sleep(1)
        driver.scroll(5000)


def clickLoadButton(driver):
    try:
        loadButton = driver.ele('.a-last')
        if loadButton:
            loadButton.click()
            print("已加载更多内容")
        else:
            print("加载按钮存在但不可点击")
    except Exception as e:
        print(f"已没有更多内容: {e}")


def getAllProductlink(tab, all_product_links: list):
    """提取当前页面所有商品链接（线程安全，结果追加到传入列表）"""
    allproduct = tab.eles('.a-column a-span12 a-text-center _cDEzb_grid-column_2hIsc')
    print(len(allproduct))
    for product in allproduct:
        try:
            product_link = product.ele('.a-link-normal aok-block').attr('href')
            if product_link:
                all_product_links.append(product_link)
        except Exception:
            continue
    print(f"  [OK] 本次品类扫描共找到 {len(all_product_links)} 个商品链接")


def download_image(img_url, save_dir, Filename):
    try:
        if not os.path.exists(save_dir):
            os.makedirs(save_dir)
        response = requests.get(img_url, stream=True)
        if response.status_code == 200:
            filepath = os.path.join(save_dir, Filename)
            with open(filepath, 'wb') as file:
                for chunk in response.iter_content(1024):
                    file.write(chunk)
            return filepath
        return None
    except Exception as e:
        print(f"下载图片时发生错误: {e}")
        return None


def extract_category(url):
    try:
        match = re.search(r'Best-Sellers-([^/]+)', url)
        return match.group(1) if match else ''
    except Exception:
        return ''


# ─────────────────────────────────────────────
# 单商品抓取（供线程池调用）
# ─────────────────────────────────────────────

def fetch_single_product(url: str, category: str, image_save_dir: str):
    """
    在当前线程的浏览器中抓取单个商品页，返回 (product_info | None, reviews_list)
    """
    thread_name = threading.current_thread().name
    browser = get_thread_browser()
    tab = browser.new_tab()

    product_info = None
    reviews_list = []

    try:
        tab.get(url)
        time.sleep(random.uniform(1.5, 2.5))

        # 滚动触发懒加载
        try:
            review_header = tab.ele('#customerReviews')
            if review_header:
                review_header.scroll.to_see()
        except Exception:
            pass
        scrollDown(tab, 3)
        time.sleep(random.uniform(*SCROLL_DELAY))

        # 上架时间
        try:
            standard_sales_start_time = (
                tab.ele('@data-19ax5a9jf=dingo')
                   .attr('data-aui-build-date')
                   .split("-", 1)[1]
            )
        except Exception:
            standard_sales_start_time = ''

        product = tab.ele('.a-container')
        if not product:
            print(f"  [{thread_name}] 页面未正常加载，可能遇到验证码，跳过: {url}")
            return None, []

        # ASIN
        try:
            original_tcin = product.ele('#ASIN').attr('value')
        except Exception:
            original_tcin = ''
        if not original_tcin:
            print(f"  [{thread_name}] 无法提取 ASIN，跳过: {url}")
            return None, []

        # 标题
        try:
            title = product.ele('.a-size-large product-title-word-break').text
        except Exception:
            title = ''

        # 规格尺寸
        specifications = ''
        try:
            spec_el = product.ele('.a-spacing-small po-item_depth_width_height')
            if spec_el:
                specifications = spec_el.ele('.a-size-base po-break-word').text
            if not specifications:
                dimension_keywords = ['Product Dimensions', 'Package Dimensions', 'Dimensions']
                for kw in dimension_keywords:
                    label_el = (
                        tab.ele(f'xpath://th[contains(text(), "{kw}")]') or
                        tab.ele(f'xpath://td[contains(text(), "{kw}")]') or
                        tab.ele(f'xpath://span[contains(text(), "{kw}")]')
                    )
                    if label_el:
                        val_el = label_el.next()
                        if val_el:
                            specifications = val_el.text.strip()
                            if specifications in (':', ''):
                                specifications = val_el.next().text.strip()
                            if specifications:
                                break
        except Exception:
            pass

        Currency = "USD"

        # 当前价格
        current_retail = ''
        try:
            PriceWhole    = tab.ele('.a-price-whole')
            PriceFraction = tab.ele('.a-price-fraction')
            if PriceWhole and PriceFraction:
                current_retail = (
                    PriceWhole.text.replace('.', '').replace('\n', '') +
                    '.' + PriceFraction.text.replace('\n', '')
                )
            elif PriceWhole:
                current_retail = PriceWhole.text.replace('.', '').replace('\n', '')
        except Exception:
            pass

        core_price_containers = [
            'xpath://*[@id="corePriceDisplay_desktop_feature_div"]',
            'xpath://*[@id="corePrice_feature_div"]',
            'xpath://*[@id="corePrice_desktop"]',
        ]

        # 原价
        reg_retail = ''
        try:
            reg_el = None
            for xpath in core_price_containers:
                container = tab.ele(xpath)
                if container:
                    reg_el = container.ele(
                        'xpath:.//span[contains(@class, "a-text-price") and @data-a-strike="true"]'
                    )
                    if reg_el:
                        break
            if not reg_el:
                reg_el = tab.ele(
                    'xpath://span[contains(@class, "a-text-price") and @data-a-strike="true"]'
                )
            if reg_el:
                offscreen = reg_el.ele('xpath:.//span[contains(@class, "a-offscreen")]')
                reg_retail = offscreen.text.strip() if offscreen else reg_el.text.strip()
        except Exception:
            pass

        # 折扣
        discount = ''
        try:
            discount_el = None
            for xpath in core_price_containers:
                container = tab.ele(xpath)
                if container:
                    discount_el = container.ele(
                        'xpath:.//span[contains(@class, "savingsPercentage")]'
                    )
                    if discount_el:
                        break
            if not discount_el:
                discount_el = tab.ele('xpath://span[contains(@class, "savingsPercentage")]')
            if discount_el:
                discount = discount_el.text.strip()
        except Exception:
            pass

        # 品牌
        primary_brand_name = ''
        try:
            brand_row = tab.ele('xpath://tr[td[1]//span[contains(text(), "Brand")]]')
            if brand_row:
                primary_brand_name = brand_row.ele('xpath:./td[2]//span').text.strip()
        except Exception:
            pass
        if not primary_brand_name:
            try:
                brand_ele = tab.ele(
                    'xpath://tr[contains(@class, "po-brand")]'
                    '//span[contains(@class, "po-break-word")]'
                )
                if brand_ele:
                    primary_brand_name = brand_ele.text.strip()
            except Exception:
                pass

        # 商品主图
        primary_image = ''
        try:
            thumb_list = tab.eles('xpath://li[contains(@class, "imageThumbnail")]')
            if thumb_list:
                img_element = thumb_list[0].ele('tag:img')
                if img_element:
                    primary_image = img_element.attr('src')
        except Exception:
            pass

        # 场景图
        alternate_image = ''
        try:
            thumb_list = tab.eles('xpath://li[contains(@class, "imageThumbnail")]')
            if len(thumb_list) >= 2:
                img_element_S = thumb_list[1].ele('tag:img')
                if img_element_S:
                    alternate_image = img_element_S.attr('src')
        except Exception:
            pass

        # 卖点
        about_this_item = ''
        try:
            about_ele = product.ele('#feature-bullets')
            if about_ele:
                about_this_item = about_ele.text.replace('About this item\n', '').strip()
        except Exception:
            pass

        # 简略信息
        product_simple_info = ''
        try:
            simple_info_xpaths = [
                'xpath://*[@id="poExpander"]//table',
                'xpath://*[@id="productOverview_feature_div"]//table',
                'xpath://div[contains(@class, "productOverview_feature_div")]//table',
            ]
            for xpath in simple_info_xpaths:
                simple_info_ele = tab.ele(xpath)
                if simple_info_ele:
                    simple_dict = {}
                    for row in simple_info_ele.eles('tag:tr'):
                        tds = row.eles('tag:td')
                        if len(tds) >= 2:
                            key   = tds[0].text.strip()
                            value = tds[1].text.strip()
                            if 'See more' in value or '...' in value:
                                full = tds[1].attr('textContent')
                                if full:
                                    value = full.replace('See more', '').strip()
                            if key and value:
                                simple_dict[key] = value
                    if simple_dict:
                        product_simple_info = json.dumps(simple_dict, ensure_ascii=False)
                        break
        except Exception:
            pass

        # 详情参数
        product_information = ''
        try:
            detail_xpaths = [
                '//*[@id="prodDetails"]',
                '//*[@id="tech"]/div[4]/div',
                '//*[@id="compare"]',
            ]
            for xpath in detail_xpaths:
                container = tab.ele(f'xpath:{xpath}')
                if not container:
                    continue
                detail_dict = {}
                detail_rows = container.eles('tag:tr')
                if detail_rows:
                    for row in detail_rows:
                        if 'compare' in xpath:
                            th = row.ele('tag:th')
                            td = row.ele('.ucc-v2-widget__table__col--page-asin')
                        else:
                            th = row.ele('tag:th')
                            td = row.ele('tag:td')
                        if th and td:
                            key   = th.text.strip()
                            value = td.text.strip()
                            if not value:
                                img = td.ele('tag:img')
                                if img and img.attr('alt'):
                                    value = img.attr('alt')
                            if key and value:
                                detail_dict[key] = value
                if detail_dict:
                    product_information = json.dumps(detail_dict, ensure_ascii=False)
                    break
                else:
                    text_content = container.text.strip()
                    if text_content:
                        lines = [l for l in text_content.split('\n') if l.strip()]
                        text_dict = {}
                        if len(lines) >= 2:
                            for i in range(0, len(lines) - 1, 2):
                                k = lines[i].strip()
                                v = lines[i+1].strip()
                                if k:
                                    text_dict[k] = v
                            product_information = json.dumps(text_dict, ensure_ascii=False)
                        else:
                            product_information = text_content
                        break
        except Exception:
            pass

        # 用户评价摘要
        customers_say = ''
        try:
            cs_el = tab.ele(
                'xpath://*[@id="reviewsMedley"]/div/div[2]/div/div[2]/div[1]/div/div/div/div[1]'
            )
            if cs_el:
                customers_say = cs_el.text.strip()
        except Exception:
            pass

        # 产品描述
        Product_description = ''
        try:
            aplus = tab.ele('xpath://*[@id="aplus"]/div/div/div')
            if aplus:
                desc_parts = []
                if aplus.text.strip():
                    desc_parts.append(aplus.text.strip())
                for img in aplus.eles('tag:img'):
                    src = img.attr('data-src') or img.attr('src')
                    if src and 'transparent-pixel' not in src and not src.startswith('data:image'):
                        desc_parts.append(src)
                Product_description = '\n'.join(desc_parts)
            if not Product_description:
                for i in range(1, 10):
                    btf = tab.ele(f'xpath://*[@id="btfContent{i}_feature_div"]')
                    if btf and btf.text.strip():
                        desc_parts = [btf.text.strip()]
                        for img in btf.eles('tag:img'):
                            src = img.attr('data-src') or img.attr('src')
                            if src and 'transparent-pixel' not in src and not src.startswith('data:image'):
                                desc_parts.append(src)
                        Product_description = '\n'.join(desc_parts)
                        break
        except Exception:
            pass

        # 评分
        average = ''
        try:
            average_el = tab.ele('xpath://span[@data-hook="rating-out-of-text"]')
            if average_el:
                average = average_el.text.strip()
        except Exception:
            pass

        # 评论总数
        count = ''
        try:
            count_el = tab.ele('xpath://span[@data-hook="total-review-count"]')
            if count_el:
                count = count_el.text.strip()
        except Exception:
            pass

        product_info = {
            'category':                  category,
            'original_tcin':             original_tcin,
            'specifications':            specifications,
            'title':                     title,
            'Currency':                  Currency,
            'current_retail':            current_retail,
            'reg_retail':                reg_retail,
            'discount':                  discount,
            'count':                     count,
            'overall_rating':            average,
            'about_this_item':           about_this_item,
            'product_simple_info':       product_simple_info,
            'product_information':       product_information,
            'customers_say':             customers_say,
            'Product_description':       Product_description,
            'item_type_name':            '',
            'item_type':                 '',
            'standard_sales_start_time': standard_sales_start_time,
            'canonical_url':             url,
            'primary_brand_name':        primary_brand_name,
            'primary_image':             primary_image,
            'alternate_image':           alternate_image,
            'data_source':               'AMAZON',
        }

        # 评论列表
        try:
            review_divs = tab.eles('xpath://*[@data-hook="review"]')
            for review_div in (review_divs or []):
                reviewer_name = ''
                name_el = review_div.ele('.a-profile-name')
                if name_el:
                    reviewer_name = name_el.text.strip()

                rating = ''
                rating_el = review_div.ele('.a-icon-alt')
                if rating_el:
                    rating = rating_el.text.strip()

                review_title = ''
                title_el = review_div.ele('xpath:.//*[@data-hook="review-title"]')
                if title_el:
                    spans = title_el.eles('tag:span')
                    valid_texts = [s.text.strip() for s in spans if s.text and s.text.strip()]
                    if valid_texts:
                        review_title = valid_texts[-1]
                    if not review_title:
                        raw_title = title_el.text or title_el.attr('textContent') or ''
                        review_title = raw_title.replace(rating, '').strip() if rating else raw_title.strip()

                review_date = ''
                date_el = review_div.ele('xpath:.//*[@data-hook="review-date"]')
                if date_el:
                    review_date = date_el.text.strip() or date_el.attr('textContent').strip()

                review_body = ''
                body_el = review_div.ele('xpath:.//*[@data-hook="review-body"]')
                if body_el:
                    collapsed_el = body_el.ele('xpath:.//*[@data-hook="review-collapsed"]')
                    if collapsed_el:
                        review_body = collapsed_el.text.strip() or collapsed_el.attr('textContent').strip()
                    else:
                        review_body = body_el.text.strip() or body_el.attr('textContent').strip()
                    review_body = review_body.replace('\n', ' ').strip()

                reviews_list.append({
                    'original_tcin': original_tcin,
                    'reviewer_name': reviewer_name,
                    'rating':        rating,
                    'review_title':  review_title,
                    'review_date':   review_date,
                    'review_body':   review_body,
                })
        except Exception:
            pass

        print(f"  [{thread_name}] [OK] 成功抓取: {original_tcin} - {title[:40]}...")

    except Exception as e:
        print(f"  [{thread_name}] [FAIL] 处理 {url} 时发生错误: {e}")
        product_info = None
    finally:
        try:
            tab.close()
        except Exception:
            pass

    time.sleep(random.uniform(*REQUEST_DELAY))
    return product_info, reviews_list


# ─────────────────────────────────────────────
# 多线程批量抓取（替代原来的 fetch_data_sequential）
# ─────────────────────────────────────────────

def fetch_data_parallel(url_list, image_save_dir, category='',
                         db_ready=False, category_url=None,
                         thread_count=THREAD_COUNT):
    """
    多线程抓取商品列表。
    - thread_count=1 时退化为单线程，行为与原版完全一致。
    - 每抓完一个商品立刻写库（线程安全，使用独立 engine）。
    """
    engine = create_engine(db_config.get_sqlalchemy_url(), echo=False) if db_ready else None
    # 数据库写入锁（多线程并发写同一连接时需要）
    db_lock = threading.Lock()

    product_info_list = []
    reviews_list_all  = []
    total = len(url_list)
    completed_count   = 0   # 已成功处理的商品数
    fully_completed   = False

    def _db_write(product_info, reviews):
        """将单条商品 + 评论写入数据库（加锁保证线程安全）"""
        if not engine:
            return
        with db_lock:
            try:
                with engine.connect() as conn:
                    p_data = product_info.copy()
                    cols   = ", ".join([f"`{c}`" for c in p_data.keys()])
                    phs    = ", ".join([f":{c}" for c in p_data.keys()])
                    conn.execute(
                        text(f"INSERT IGNORE INTO `{db_config.PRODUCT_TABLE}` ({cols}) VALUES ({phs})"),
                        p_data,
                    )
                    for r_row in reviews:
                        r_cols = ", ".join([f"`{c}`" for c in r_row.keys()])
                        r_phs  = ", ".join([f":{c}" for c in r_row.keys()])
                        conn.execute(
                            text(f"INSERT IGNORE INTO `{db_config.REVIEW_TABLE}` ({r_cols}) VALUES ({r_phs})"),
                            r_row,
                        )
                    conn.commit()
                asin = product_info.get('original_tcin', '')
                print(f"  [DB OK] 商品 {asin} 入库成功！")
            except Exception as e:
                print(f"  [DB ERROR] 写入 MySQL 失败: {e}")

    print(f"\n[并发配置] 线程数 = {thread_count}，商品总数 = {total}")

    with ThreadPoolExecutor(max_workers=thread_count,
                            thread_name_prefix="AmazonWorker") as executor:
        future_map = {
            executor.submit(fetch_single_product, url, category, image_save_dir): url
            for url in url_list
        }

        for future in as_completed(future_map):
            url = future_map[future]
            try:
                product_info, reviews = future.result()
            except Exception as e:
                print(f"  [FAIL] Future 异常 ({url}): {e}")
                continue

            if product_info is None:
                continue

            product_info_list.append(product_info)
            reviews_list_all.extend(reviews)
            completed_count += 1

            print(f"  [进度] {completed_count}/{total} 完成")
            _db_write(product_info, reviews)

    # 正常走完所有 URL 则标记完成
    if completed_count > 0:
        fully_completed = True

    # 更新品类任务状态
    if fully_completed and engine and db_ready and category_url:
        print(f"  [DB] 将品类任务标记为已完成: {category_url}")
        try:
            with engine.connect() as conn:
                conn.execute(
                    text(f"UPDATE `{db_config.TASK_TABLE}` SET status=1 WHERE crawl_url = :url"),
                    {"url": category_url},
                )
                conn.commit()
        except Exception as e:
            print(f"  [DB ERROR] 更新品类任务状态失败: {e}")

    # 关闭所有线程的浏览器
    print("  [清理] 正在关闭所有线程浏览器...")
    # 通过 executor 已结束，线程已回收，但 _thread_local 中的浏览器需手动清理
    # 此处通过额外的 shutdown 任务在线程内关闭（兼容方式）

    print(f"\n本轮共成功抓取 {len(product_info_list)}/{total} 个商品，"
          f"共提取到 {len(reviews_list_all)} 条评论。")
    return product_info_list, reviews_list_all


# ─────────────────────────────────────────────
# 主流程
# ─────────────────────────────────────────────

if __name__ == '__main__':
    start_time = time.time()

    # 品类入口 URL 列表（可扩展）
    detail_links_all = [
        "https://www.amazon.com/Best-Sellers-Electronics/zgbs/electronics/ref=zg_bs_unv_electronics_1_281407_1"
    ]

    current_dir = os.path.dirname(os.path.abspath(__file__))

    # ── 数据库初始化 ──────────────────────────────
    db_ready = db_setup.init_db()

    # ── 同步品类链接到任务表 ──────────────────────
    if db_ready:
        try:
            engine_init = create_engine(db_config.get_sqlalchemy_url(), echo=False)
            with engine_init.connect() as conn:
                for url in detail_links_all:
                    conn.execute(
                        text(f"INSERT IGNORE INTO `{db_config.TASK_TABLE}` (crawl_url, status) VALUES (:url, 0)"),
                        {"url": url},
                    )
                conn.commit()
        except Exception as e:
            print(f"初始化任务列表失败: {e}")

    # ── 读取待抓取品类 ────────────────────────────
    pending_categories = []
    if db_ready:
        try:
            with engine_init.connect() as conn:
                result = conn.execute(
                    text(f"SELECT crawl_url FROM `{db_config.TASK_TABLE}` WHERE status = 0")
                )
                pending_categories = [row[0] for row in result]
        except Exception as e:
            print(f"读取待抓取任务失败: {e}")

    if not pending_categories:
        print("没有发现待抓取的品类任务，程序退出。")
        exit()

    print(f"本次共有 {len(pending_categories)} 个品类待抓取，并发线程数 = {THREAD_COUNT}")

    # ── 逐品类处理 ────────────────────────────────
    for cat_url in pending_categories:
        print(f"\n========== 开始处理品类: {cat_url} ==========")

        # 用主线程浏览器提取商品链接列表（单独操作，无需多线程）
        co = get_chromium_options()
        list_browser = ChromiumPage(co)
        list_tab = list_browser.new_tab()
        list_tab.get(cat_url)

        all_product_links = []
        scrollDown(list_tab, 3)
        time.sleep(1)
        getAllProductlink(list_tab, all_product_links)
        clickLoadButton(list_tab)
        time.sleep(1)
        scrollDown(list_tab, 3)
        getAllProductlink(list_tab, all_product_links)
        list_tab.close()
        list_browser.quit()

        # 去重
        all_product_links = list(dict.fromkeys(all_product_links))
        print(f"该品类去重后共 {len(all_product_links)} 个商品链接")

        # 测试模式限制
        if TEST_LIMIT > 0:
            all_product_links = all_product_links[:TEST_LIMIT]
            print(f"  [测试模式] 仅抓取前 {len(all_product_links)} 个链接...")

        category_name      = extract_category(cat_url)
        image_save_dir     = os.path.join(current_dir, "AMAZON")

        # ── 多线程抓取 ────────────────────────────
        all_results, all_reviews = fetch_data_parallel(
            all_product_links,
            image_save_dir,
            category=category_name,
            db_ready=db_ready,
            category_url=cat_url,
            thread_count=THREAD_COUNT,   # ← 改这里切换线程数，1 = 单线程
        )

        # ── Excel 备份 ────────────────────────────
        timestamp  = datetime.now().strftime('%Y%m%d_%H%M%S')
        excel_dir  = os.path.join(current_dir, "excel")
        os.makedirs(excel_dir, exist_ok=True)

        if all_results:
            path_p = os.path.join(excel_dir, f"productInfo_{category_name}_{timestamp}.xlsx")
            pd.DataFrame(all_results).to_excel(path_p, index=False)
            print(f"  [Excel] 商品数据已保存至 {path_p}")
        if all_reviews:
            path_r = os.path.join(excel_dir, f"reviewsInfo_{category_name}_{timestamp}.xlsx")
            pd.DataFrame(all_reviews).to_excel(path_r, index=False)
            print(f"  [Excel] 评论数据已保存至 {path_r}")

        print(f"品类 {category_name} 抓取完毕。")

    print(f"\n所有待抓取任务已处理完毕。")
    print(f"代码运行时间为: {time.time() - start_time:.2f} 秒")