#!/usr/bin/env python3
"""
更新数据库结构，为EconomicIndicator表添加fred_url字段并填充数据
"""

import os
import sys
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

# 将项目根目录添加到Python路径中
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

# 使用项目根目录的数据库文件
DATABASE_URL = "sqlite:///" + os.path.join(os.path.dirname(os.path.abspath(__file__)), "fomc_data.db")

def update_database():
    """更新数据库结构"""
    engine = create_engine(DATABASE_URL)
    
    # 检查fred_url列是否已存在
    with engine.connect() as connection:
        result = connection.execute(text("PRAGMA table_info(economic_indicators)"))
        columns = [row[1] for row in result]
        
        if 'fred_url' not in columns:
            print("添加fred_url列...")
            connection.execute(text("ALTER TABLE economic_indicators ADD COLUMN fred_url VARCHAR(255)"))
            connection.commit()
            print("fred_url列添加成功")
        else:
            print("fred_url列已存在")
    
    # 更新所有指标的fred_url
    Session = sessionmaker(bind=engine)
    session = Session()
    
    try:
        # 获取所有指标
        indicators = session.execute(text("SELECT id, code FROM economic_indicators")).fetchall()
        
        for indicator in indicators:
            indicator_id, code = indicator
            # 生成FRED URL
            fred_url = f"https://fred.stlouisfed.org/series/{code}"
            
            # 更新数据库
            session.execute(
                text("UPDATE economic_indicators SET fred_url = :url WHERE id = :id"),
                {"url": fred_url, "id": indicator_id}
            )
        
        session.commit()
        print(f"已更新 {len(indicators)} 个指标的FRED URL")
        
    except Exception as e:
        session.rollback()
        print(f"更新失败: {e}")
    finally:
        session.close()

if __name__ == "__main__":
    update_database()