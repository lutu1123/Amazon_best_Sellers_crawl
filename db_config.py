# db_config.py

# 数据库连接配置
# 请在此处填写您的 MySQL 数据库实际信息
DB_HOST = '127.0.0.1'
DB_PORT = 3306
DB_USER = 'root'
DB_PASS = '123456'
DB_NAME = 'amazon_crawl'

# 表名配置
PRODUCT_TABLE = 'amazon_products'
REVIEW_TABLE = 'amazon_reviews'
TASK_TABLE = 'amazon_tasks'

def get_sqlalchemy_url():
    """
    返回用于 sqlalchemy 的连接字符串
    """
    return f"mysql+pymysql://{DB_USER}:{DB_PASS}@{DB_HOST}:{DB_PORT}/{DB_NAME}?charset=utf8mb4"
