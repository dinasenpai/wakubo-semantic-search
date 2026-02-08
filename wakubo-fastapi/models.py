from sqlalchemy import Column, Integer, String, Text, DateTime
from sqlalchemy.sql import func
from db import Base

class ShopToken(Base):
    """Store access token per shop"""
    __tablename__ = "shop_tokens"
    
    id = Column(Integer, primary_key=True)
    shop = Column(String, unique=True, index=True, nullable=False)  # store-name.myshopify.com
    access_token = Column(String, nullable=False)
    installed_at = Column(DateTime, server_default=func.now())

class Product(Base):
    """Product catalog synced from Shopify"""
    __tablename__ = "products"
    
    id = Column(Integer, primary_key=True)
    shop = Column(String, index=True, nullable=False)
    shopify_gid = Column(String, unique=True, index=True, nullable=False)  # gid://shopify/Product/123
    
    title = Column(String, index=True, default="")
    description = Column(Text, default="")
    handle = Column(String, index=True, default="")
    image_url = Column(String, default="")
    product_url = Column(String, default="")
    
    synced_at = Column(DateTime, server_default=func.now(), onupdate=func.now())
