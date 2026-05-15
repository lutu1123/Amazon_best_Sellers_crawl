import pymysql
import db_config

def init_db():
    """
    初始化数据库和表结构。
    如果数据库或表不存在，则创建它们。
    """
    print("正在检查/创建数据库和表...")
    
    # 1. 连接 MySQL 服务器（不指定数据库），用于创建数据库
    try:
        conn = pymysql.connect(
            host=db_config.DB_HOST,
            port=db_config.DB_PORT,
            user=db_config.DB_USER,
            password=db_config.DB_PASS,
            charset='utf8mb4'
        )
    except Exception as e:
        print(f"无法连接到 MySQL 服务器: {e}")
        print("请检查 db_config.py 中的数据库配置是否正确，以及 MySQL 服务是否已启动。")
        return False
        
    cursor = conn.cursor()
    
    # 2. 创建数据库（如果不存在）
    try:
        cursor.execute(f"CREATE DATABASE IF NOT EXISTS `{db_config.DB_NAME}` DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;")
        conn.select_db(db_config.DB_NAME)
    except Exception as e:
        print(f"创建或选择数据库失败: {e}")
        conn.close()
        return False

    # 3. 创建产品表
    create_product_table_sql = f"""
    CREATE TABLE IF NOT EXISTS `{db_config.PRODUCT_TABLE}` (
        `id` INT AUTO_INCREMENT PRIMARY KEY,
        `category` VARCHAR(255),
        `original_tcin` VARCHAR(100) UNIQUE,
        `specifications` TEXT,
        `title` TEXT,
        `Currency` VARCHAR(50),
        `current_retail` VARCHAR(100),
        `reg_retail` VARCHAR(100),
        `discount` VARCHAR(100),
        `count` VARCHAR(100),
        `overall_rating` VARCHAR(50),
        `about_this_item` TEXT,
        `product_simple_info` TEXT,
        `product_information` TEXT,
        `customers_say` TEXT,
        `Product_description` LONGTEXT,
        `item_type_name` VARCHAR(255),
        `item_type` VARCHAR(255),
        `standard_sales_start_time` VARCHAR(255),
        `canonical_url` TEXT,
        `primary_brand_name` VARCHAR(255),
        `primary_image` TEXT,
        `alternate_image` TEXT,
        `data_source` VARCHAR(100),
        `crawl_time` TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
    """
    
    # 4. 创建评论表
    create_review_table_sql = f"""
    CREATE TABLE IF NOT EXISTS `{db_config.REVIEW_TABLE}` (
        `id` INT AUTO_INCREMENT PRIMARY KEY,
        `original_tcin` VARCHAR(100),
        `reviewer_name` VARCHAR(255),
        `rating` VARCHAR(50),
        `review_title` TEXT,
        `review_date` VARCHAR(255),
        `review_body` TEXT,
        `crawl_time` TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        INDEX `idx_original_tcin` (`original_tcin`),
        UNIQUE KEY `uk_review` (`original_tcin`, `reviewer_name`(100), `review_date`(50))
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
    """
    
    # 5. 创建任务表
    create_task_table_sql = f"""
    CREATE TABLE IF NOT EXISTS `{db_config.TASK_TABLE}` (
        `id` INT AUTO_INCREMENT PRIMARY KEY,
        `crawl_url` VARCHAR(700) UNIQUE,
        `level` INT DEFAULT 0,
        `status` INT DEFAULT 0,
        `created_at` TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        `updated_at` TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
    """
    
    try:
        cursor.execute(create_product_table_sql)
        cursor.execute(create_review_table_sql)
        cursor.execute(create_task_table_sql)
        conn.commit()
        print(f"数据库 [{db_config.DB_NAME}] 及表 [{db_config.PRODUCT_TABLE}], [{db_config.REVIEW_TABLE}], [{db_config.TASK_TABLE}] 准备就绪！")
        success = True
    except Exception as e:
        print(f"创建表失败: {e}")
        success = False
    finally:
        cursor.close()
        conn.close()
        
    return success

if __name__ == "__main__":
    init_db()
