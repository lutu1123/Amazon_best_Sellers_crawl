from DrissionPage import ChromiumPage, ChromiumOptions
from sqlalchemy import create_engine, text
import db_config
import db_setup
import time
import random
from urllib.parse import urljoin

# ================= 配置区 =================
START_URL = "https://www.amazon.com/Best-Sellers-Electronics/zgbs/electronics/ref=zg_bs_unv_electronics_1_281407_1"
MAX_DEPTH = 6  # 最大的嵌套深度
BROWSER_PATH = r'C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe'
# ==========================================

def init_engine():
    return create_engine(db_config.get_sqlalchemy_url(), echo=False)

def get_sub_categories(tab, current_level):
    """
    提取侧边栏中当前品类的子类链接
    """
    sub_links = []
    try:
        # 1. 寻找当前选中的品类（带有 Current 标识或特定选中类名）
        # 根据用户提供的 HTML，选中项包含 _p13n-zg-nav-tree-all_style_zg-selected__1SfhQ
        selected_el = tab.ele('xpath://span[contains(@class, "zg-selected")]') or \
                      tab.ele('xpath://span[contains(text(), "(Current)")]')
        
        if not selected_el:
            print("  [WARN] 未找到当前选中的品类标识，尝试通用匹配...")
            # 兜底方案：找最后一层嵌套的 ul 里的所有链接
            nav_tree = tab.eles('xpath://ul[contains(@class, "zg-browse-group")]')
            if nav_tree:
                last_ul = nav_tree[-1]
                links = last_ul.eles('tag:a')
                for a in links:
                    href = a.attr('href')
                    if href:
                        sub_links.append(urljoin(tab.url, href))
            return sub_links

        # 2. 找到当前品类所在的 li
        parent_li = selected_el.parent().parent() # span -> span -> li
        
        # 3. 在 Amazon 结构中，子类通常在当前 li 的下一个 li 兄弟节点的 ul 中
        next_li = parent_li.next()
        if next_li:
            child_ul = next_li.ele('tag:ul')
            if child_ul:
                links = child_ul.eles('tag:a')
                for a in links:
                    href = a.attr('href')
                    if href:
                        full_url = urljoin(tab.url, href)
                        sub_links.append(full_url)
        
        # 如果还是没找到，尝试在当前 li 的后续结构中找所有 a
        if not sub_links:
            # 寻找紧跟在选定项之后的 ul
            child_ul = parent_li.ele('xpath:following-sibling::li//ul')
            if child_ul:
                links = child_ul.eles('tag:a')
                for a in links:
                    href = a.attr('href')
                    if href:
                        sub_links.append(urljoin(tab.url, href))

    except Exception as e:
        print(f"  [ERROR] 提取子类链接失败: {e}")
    
    return list(set(sub_links))

def main():
    print("=== 亚马逊品类深度挖掘工具启动 ===")
    
    # 1. 初始化数据库
    if not db_setup.init_db():
        print("数据库初始化失败，请检查配置。")
        return

    engine = init_engine()
    
    # 2. 设置浏览器
    co = ChromiumOptions().set_paths(browser_path=BROWSER_PATH)
    co.set_argument('--disable-blink-features=AutomationControlled')
    browser = ChromiumPage(co)
    tab = browser.new_tab()

    # 3. 准备抓取队列 (URL, level)
    # 首先手动存入初始链接
    with engine.connect() as conn:
        conn.execute(text(f"INSERT IGNORE INTO `{db_config.TASK_TABLE}` (crawl_url, level, status) VALUES (:url, 0, 0)"), 
                     {"url": START_URL})
        conn.commit()

    queue = [(START_URL, 0)]
    visited = {START_URL}

    idx = 0
    while idx < len(queue):
        curr_url, curr_level = queue[idx]
        idx += 1
        
        if curr_level >= MAX_DEPTH:
            continue

        print(f"\n[Level {curr_level}] 正在分析: {curr_url}")
        
        try:
            tab.get(curr_url)
            time.sleep(random.uniform(2, 4)) # 等待侧边栏渲染
            
            # 提取子类
            subs = get_sub_categories(tab, curr_level)
            print(f"  找到 {len(subs)} 个子品类")
            
            if subs:
                next_level = curr_level + 1
                with engine.connect() as conn:
                    for sub_url in subs:
                        # 存入数据库
                        conn.execute(text(f"INSERT IGNORE INTO `{db_config.TASK_TABLE}` (crawl_url, level, status) VALUES (:url, :lvl, 0)"), 
                                     {"url": sub_url, "lvl": next_level})
                        
                        # 如果还没达到最大深度，加入队列继续挖掘
                        if sub_url not in visited and next_level < MAX_DEPTH:
                            visited.add(sub_url)
                            queue.append((sub_url, next_level))
                    conn.commit()
                print(f"  [OK] Level {next_level} 链接已入库")
                
        except Exception as e:
            print(f"  [FAIL] 访问失败: {e}")
        
        # 随机延时避免封禁
        time.sleep(random.uniform(1, 2))

    print("\n=== 所有品类链接挖掘完毕！ ===")
    browser.quit()

if __name__ == "__main__":
    main()
