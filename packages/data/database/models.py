# Database models for FOMC project

from sqlalchemy import Column, Integer, String, Float, DateTime, Text, ForeignKey, UniqueConstraint
from sqlalchemy.orm import relationship
from .base import Base

class IndicatorCategory(Base):
    """
    Model for storing indicator categories (sectors/boards)
    """
    __tablename__ = 'indicator_categories'
    
    id = Column(Integer, primary_key=True)
    name = Column(String(100), nullable=False, unique=True)  # 板块名称，如"非农就业"、"CPI"
    description = Column(Text)
    parent_id = Column(Integer, ForeignKey('indicator_categories.id'), nullable=True)  # 支持多级分类
    level = Column(Integer, default=1)  # 层级：1=板块，2=子类别，3=具体指标
    sort_order = Column(Integer, default=0)  # 排序顺序
    
    # Self-referential relationship for hierarchy
    parent = relationship("IndicatorCategory", remote_side=[id])
    children = relationship("IndicatorCategory", overlaps="parent")
    
    # One-to-many relationship with indicators
    indicators = relationship("EconomicIndicator", back_populates="category", overlaps="parent")
    
    def __repr__(self):
        return f"<IndicatorCategory(name='{self.name}', level={self.level})>"

class EconomicIndicator(Base):
    """
    Model for storing economic indicators from FRED
    """
    __tablename__ = 'economic_indicators'
    
    id = Column(Integer, primary_key=True)
    name = Column(String(100), nullable=False)  # 指标名称，如"非农就业总数"
    code = Column(String(50), unique=True, nullable=False)  # FRED series ID
    english_name = Column(String(200))  # 英文指标名称
    description = Column(Text)
    frequency = Column(String(20))  # Daily, Weekly, Monthly, Quarterly, Annual
    units = Column(String(50))
    seasonal_adjustment = Column(String(50))
    last_updated = Column(DateTime)
    category_id = Column(Integer, ForeignKey('indicator_categories.id'), nullable=True)
    sort_order = Column(Integer, default=0)  # 排序顺序
    fred_url = Column(String(255))  # FRED数据平台的链接地址
    
    # Many-to-one relationship with category
    category = relationship("IndicatorCategory", back_populates="indicators")
    
    # One-to-many relationship with data points
    data_points = relationship("EconomicDataPoint", back_populates="indicator", cascade="all, delete-orphan")
    
    def __repr__(self):
        return f"<EconomicIndicator(name='{self.name}', code='{self.code}')>"

class EconomicDataPoint(Base):
    """
    Model for individual data points of economic indicators
    """
    __tablename__ = 'economic_data_points'
    __table_args__ = (
        UniqueConstraint('indicator_id', 'date', name='uq_indicator_date'),
    )
    
    id = Column(Integer, primary_key=True)
    indicator_id = Column(Integer, ForeignKey('economic_indicators.id'), nullable=False)  # Foreign key to EconomicIndicator
    date = Column(DateTime, nullable=False)
    value = Column(Float)
    
    # Many-to-one relationship with indicator
    indicator = relationship("EconomicIndicator", back_populates="data_points")
    
    def __repr__(self):
        return f"<EconomicDataPoint(indicator_id={self.indicator_id}, date='{self.date}', value={self.value})>"
