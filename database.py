"""
Database abstraction layer with SQLAlchemy
Provides connection pooling and ORM models for MySQL
"""
from sqlalchemy import create_engine, Column, Integer, String, Float, DateTime, Text, Index, event, Boolean, JSON
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, scoped_session
from sqlalchemy.pool import QueuePool
from contextlib import contextmanager
from datetime import datetime
from config import config

Base = declarative_base()

class Proxy(Base):
    """Proxy model - maps to 'proxies' table"""
    __tablename__ = 'proxies'
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    
    # Proxy identity
    protocol = Column(String(10), nullable=False)
    ip = Column(String(45), nullable=False)  # IPv6 support
    port = Column(Integer, nullable=False)
    username = Column(String(255), nullable=False, default='')
    password = Column(String(255), nullable=False, default='')
    resolved_ip = Column(String(45), nullable=True)
    cost = Column(Float, nullable=True, default=1.0)
    
    # Health metrics
    alive_hits = Column(Integer, default=0)
    last_alive = Column(DateTime, nullable=True)
    last_checked = Column(DateTime, nullable=True)
    fail_hits = Column(Integer, default=0)
    last_fail = Column(DateTime, nullable=True)
    speed_ms = Column(Integer, nullable=True)
    speed_history = Column(JSON, nullable=True)  # Store last 10 speeds for jitter calculation
    total_checks = Column(Integer, default=0)   # Total checks (alive_hits + fail_hits)
    
    # Cost components for debugging/transparency
    latency_score = Column(Float, nullable=True)   # Speed component (40%)
    reliability = Column(Float, nullable=True)     # Success rate (40%)
    jitter_score = Column(Float, nullable=True)    # Consistency (15%)
    recency_score = Column(Float, nullable=True)   # Freshness (5%)
    previous_cost = Column(Float, nullable=True)  # Previous cost for historical analysis
    
    is_cooling = Column(Integer, default=0)  # 1 if recently failed (was working, now 0.99)
    consecutive_fails = Column(Integer, default=0)  # Track consecutive failures
    status = Column(String(20), default='untested')  # untested, alive, flaky, cooling, dead
    previous_state = Column(String(20), nullable=True)  # Previous state for tracking transitions
    last_transition = Column(String(10), nullable=True)  # Last transition value: +2, +1-1, -2
    
    # Geo / network
    continent = Column(String(100), nullable=True)
    continentCode = Column(String(10), nullable=True)
    country = Column(String(100), nullable=True)
    countryCode = Column(String(10), nullable=True)
    region = Column(String(100), nullable=True)
    regionName = Column(String(100), nullable=True)
    city = Column(String(100), nullable=True)
    district = Column(String(100), nullable=True)
    zip = Column(String(20), nullable=True)
    lat = Column(Float, nullable=True)
    lon = Column(Float, nullable=True)
    timezone = Column(String(50), nullable=True)
    isp = Column(String(255), nullable=True)
    org = Column(String(255), nullable=True)
    asn = Column(String(255), nullable=True)
    asname = Column(String(255), nullable=True)
    mobile = Column(Integer, nullable=True)  # TINYINT in MySQL
    proxy = Column(Integer, nullable=True)
    hosting = Column(Integer, nullable=True)
    
    # Meta
    last_geo = Column(DateTime, nullable=True)
    
    __table_args__ = (
        Index('idx_unique_proxy', 'protocol', 'ip', 'port', 'username', 'password', unique=True),
        Index('idx_protocol', 'protocol'),
        Index('idx_cost', 'cost'),
        Index('idx_status', 'status'),
        Index('idx_country', 'countryCode'),
        Index('idx_isp', 'isp'),
        Index('idx_alive_hits', 'alive_hits'),
        Index('idx_fail_hits', 'fail_hits'),
        Index('idx_last_checked', 'last_checked'),
        Index('idx_protocol_cost', 'protocol', 'cost'),
        Index('idx_health', 'alive_hits', 'fail_hits'),
        {'mysql_engine': 'InnoDB', 'mysql_charset': 'utf8mb4'}
    )
    
    def to_dict(self):
        """Convert model to dictionary"""
        return {
            'id': self.id,
            'protocol': self.protocol,
            'ip': self.ip,
            'port': self.port,
            'username': self.username,
            'password': self.password,
            'resolved_ip': self.resolved_ip,
            'cost': self.cost,
            'alive_hits': self.alive_hits,
            'last_alive': self.last_alive.isoformat() if self.last_alive else None,
            'last_checked': self.last_checked.isoformat() if self.last_checked else None,
            'fail_hits': self.fail_hits,
            'last_fail': self.last_fail.isoformat() if self.last_fail else None,
            'speed_ms': self.speed_ms,
            'speed_history': self.speed_history,
            'total_checks': self.total_checks,
            'latency_score': self.latency_score,
            'reliability': self.reliability,
            'jitter_score': self.jitter_score,
            'recency_score': self.recency_score,
            'previous_cost': self.previous_cost,
            'is_cooling': self.is_cooling,
            'consecutive_fails': self.consecutive_fails,
            'continent': self.continent,
            'continentCode': self.continentCode,
            'country': self.country,
            'countryCode': self.countryCode,
            'region': self.region,
            'regionName': self.regionName,
            'city': self.city,
            'district': self.district,
            'zip': self.zip,
            'lat': self.lat,
            'lon': self.lon,
            'timezone': self.timezone,
            'isp': self.isp,
            'org': self.org,
            'asn': self.asn,
            'asname': self.asname,
            'mobile': self.mobile,
            'proxy': self.proxy,
            'hosting': self.hosting,
            'last_geo': self.last_geo.isoformat() if self.last_geo else None,
            'status': self.status,
            'previous_state': self.previous_state,
            'last_transition': self.last_transition,
        }

    @staticmethod
    def calculate_status(consecutive_fails):
        if consecutive_fails >= 2:
            return 'dead'
        return 'alive'

    def update_status(self):
        """Status is managed by the state machine in runner.py"""
        pass


class User(Base):
    """User model for RBAC"""
    __tablename__ = 'users'
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    username = Column(String(50), unique=True, nullable=False)
    password_hash = Column(String(128), nullable=False)
    role = Column(String(20), default='user')  # admin, superadmin, user
    custom_permissions = Column(JSON, default={})
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    last_login = Column(DateTime, nullable=True)
    
    def to_dict(self):
        return {
            'id': self.id,
            'username': self.username,
            'role': self.role,
            'custom_permissions': self.custom_permissions,
            'is_active': self.is_active,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'last_login': self.last_login.isoformat() if self.last_login else None,
        }


class Token(Base):
    """JWT Token storage"""
    __tablename__ = 'tokens'
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, nullable=False)
    token = Column(String(500), nullable=False)
    expires_at = Column(DateTime, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    
    __table_args__ = (
        Index('idx_token_user', 'user_id'),
        Index('idx_token', 'token'),
        Index('idx_token_expires', 'expires_at'),
        {'mysql_engine': 'InnoDB', 'mysql_charset': 'utf8mb4'}
    )


class MonitorSession(Base):
    """Monitor session for pause/resume tracking"""
    __tablename__ = 'monitor_sessions'
    
    id = Column(String(64), primary_key=True)
    started_at = Column(DateTime, default=datetime.utcnow)
    config_snapshot = Column(Text, nullable=True)
    total_proxies = Column(Integer, default=0)
    tested_count = Column(Integer, default=0)
    alive_count = Column(Integer, default=0)
    dead_count = Column(Integer, default=0)
    other_count = Column(Integer, default=0)
    status = Column(String(20), default='running')
    
    __table_args__ = (
        Index('idx_session_status', 'status'),
        {'mysql_engine': 'InnoDB', 'mysql_charset': 'utf8mb4'}
    )


class MonitorTested(Base):
    """Track which proxies were tested in a session"""
    __tablename__ = 'monitor_tested'
    
    session_id = Column(String(64), primary_key=True)
    proxy_id = Column(Integer, primary_key=True)
    tested_at = Column(DateTime, default=datetime.utcnow)
    
    __table_args__ = (
        Index('idx_tested_session', 'session_id'),
        Index('idx_tested_proxy', 'proxy_id'),
        {'mysql_engine': 'InnoDB', 'mysql_charset': 'utf8mb4'}
    )


class Database:
    """Database manager with connection pooling"""
    
    def __init__(self):
        self.engine = None
        self.Session = None
        self._init_engine()
    
    def _init_engine(self):
        """Initialize database engine with connection pooling"""
        database_url = config.get_database_url()
        
        self.engine = create_engine(
            database_url,
            poolclass=QueuePool,
            pool_size=config.DB_POOL_SIZE,
            max_overflow=config.DB_MAX_OVERFLOW,
            pool_timeout=config.DB_POOL_TIMEOUT,
            pool_recycle=config.DB_POOL_RECYCLE,
            pool_pre_ping=True,  # Verify connections before use
            echo=False,  # Set to True for SQL debugging
        )
        
        # Create session factory
        self.Session = scoped_session(sessionmaker(bind=self.engine))
    
    def create_tables(self):
        """Create all tables"""
        Base.metadata.create_all(self.engine)
        print("[+] Database tables created successfully")
    
    def drop_tables(self):
        """Drop all tables (use with caution!)"""
        Base.metadata.drop_all(self.engine)
        print("[!] Database tables dropped")
    
    @contextmanager
    def session(self):
        """Context manager for database sessions
        
        Usage:
            with db.session() as session:
                proxy = session.query(Proxy).first()
                session.commit()
        """
        session = self.Session()
        try:
            yield session
            session.commit()
        except Exception as e:
            session.rollback()
            raise e
        finally:
            session.close()
    
    def get_session(self):
        """Get a new session (for advanced use)"""
        return self.Session()
    
    def close(self):
        """Close all connections"""
        if self.Session:
            self.Session.remove()
        if self.engine:
            self.engine.dispose()


# Global database instance
db = Database()

# Convenience functions for common operations
def init_db():
    """Initialize database - create tables"""
    db.create_tables()

def get_db_session():
    """Get database session context manager"""
    return db.session()

def insert_proxy(protocol, ip, port, username='', password=''):
    """Insert a single proxy (used by importer)"""
    with db.session() as session:
        # Check if exists
        existing = session.query(Proxy).filter_by(
            protocol=protocol,
            ip=ip,
            port=port,
            username=username or '',
            password=password or ''
        ).first()
        
        if existing:
            return False  # Already exists
        
        proxy = Proxy(
            protocol=protocol,
            ip=ip,
            port=port,
            username=username or '',
            password=password or ''
        )
        session.add(proxy)
        return True

def get_proxy_count():
    """Get total proxy count"""
    with db.session() as session:
        return session.query(Proxy).count()

def get_all_proxies():
    """Get all proxies as list of dicts"""
    with db.session() as session:
        proxies = session.query(Proxy).all()
        return [p.to_dict() for p in proxies]
