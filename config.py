"""
Configuration management for Proxy Pool
Loads settings from environment variables
"""
import os
from dotenv import load_dotenv
from pathlib import Path

# Load environment variables from .env file
env_path = Path(__file__).parent / '.env'
load_dotenv(dotenv_path=env_path)

class Config:
    """Application configuration"""
    
    # Database Configuration
    DB_HOST = os.getenv('DB_HOST', 'localhost')
    DB_PORT = int(os.getenv('DB_PORT', 3306))
    DB_USER = os.getenv('DB_USER', 'proxypool')
    DB_PASS = os.getenv('DB_PASS', '')
    DB_NAME = os.getenv('DB_NAME', 'proxypool')
    # Local/dev safe default: SQLite. Production MySQL must be explicit via DB_TYPE=mysql.
    DB_TYPE = os.getenv('DB_TYPE', 'sqlite')
    
    # Connection Pooling
    DB_POOL_SIZE = int(os.getenv('DB_POOL_SIZE', 20))
    DB_MAX_OVERFLOW = int(os.getenv('DB_MAX_OVERFLOW', 30))
    DB_POOL_TIMEOUT = int(os.getenv('DB_POOL_TIMEOUT', 30))
    DB_POOL_RECYCLE = int(os.getenv('DB_POOL_RECYCLE', 3600))
    
    # Legacy SQLite (for migration)
    SQLITE_DB_PATH = os.getenv('SQLITE_DB_PATH', 'proxies.db')
    
    # Build Database URL
    @classmethod
    def get_database_url(cls):
        """Returns SQLAlchemy database URL"""
        if getattr(cls, "DB_TYPE", "sqlite").lower() == "sqlite":
            return cls.get_sqlite_url()
        return f"mysql+pymysql://{cls.DB_USER}:{cls.DB_PASS}@{cls.DB_HOST}:{cls.DB_PORT}/{cls.DB_NAME}"
    
    # Alternative SQLite URL (for migration)
    @classmethod
    def get_sqlite_url(cls):
        """Returns SQLite URL for migration"""
        return f"sqlite:///{cls.SQLITE_DB_PATH}"

# Singleton instance
config = Config()
