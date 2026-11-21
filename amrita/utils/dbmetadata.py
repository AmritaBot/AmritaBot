from dataclasses import asdict, dataclass
from datetime import datetime
from enum import Enum
from typing import Any, Literal

from nonebot import logger
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.ext.asyncio.engine import AsyncConnection, AsyncEngine

# 定义支持的数据库类型
DatabaseType = Literal["sqlite", "mysql", "mariadb", "postgresql"]


# 枚举定义
class LockMode(str, Enum):
    SHARED = "shared"
    EXCLUSIVE = "exclusive"
    UPDATE = "update"
    ACCESS_SHARE = "access_share"
    ROW_SHARE = "row_share"
    ROW_EXCLUSIVE = "row_exclusive"


# 定义返回的dataclasses
@dataclass
class ConnectionStats:
    """连接统计信息"""

    total_connections: int = 0
    active_connections: int = 0
    idle_connections: int = 0
    max_allowed_connections: int | None = None
    connection_utilization_percent: float | None = None
    longest_query_seconds: float | None = None
    waiting_connections: int | None = None


@dataclass
class CacheEfficiency:
    """缓存效率统计"""

    buffer_pool_hit_ratio: float | None = None
    heap_hit_ratio: float | None = None
    index_hit_ratio: float | None = None
    logical_reads: int | None = None
    physical_reads: int | None = None
    cache_size_mb: float | None = None
    cache_used_percent: float | None = None


@dataclass
class TableActivity:
    """表活动统计"""

    table_name: str
    schema_name: str | None = None
    full_scans: int | None = None
    rows_scanned: int | None = None
    rows_inserted: int | None = None
    rows_updated: int | None = None
    rows_deleted: int | None = None
    live_rows: int | None = None
    dead_rows: int | None = None
    total_size_mb: float | None = None
    index_size_mb: float | None = None
    last_vacuum: datetime | None = None
    last_analyze: datetime | None = None


@dataclass
class IndexUsage:
    """索引使用情况"""

    index_name: str
    table_name: str
    schema_name: str | None = None
    scan_count: int | None = None
    rows_fetched: int | None = None
    cardinality: int | None = None
    unique: bool | None = None
    size_mb: float | None = None
    definition: str | None = None
    last_used: datetime | None = None


@dataclass
class LockInfo:
    """锁信息"""

    lock_type: str
    lock_mode: str
    lock_count: int = 1
    waiting_count: int | None = None
    blocked_pids: list[int] | None = None
    blocked_queries: list[str] | None = None


@dataclass
class QueryStats:
    """查询统计"""

    query_hash: str | None = None
    query_text: str | None = None
    total_executions: int | None = None
    total_time_ms: float | None = None
    avg_time_ms: float | None = None
    min_time_ms: float | None = None
    max_time_ms: float | None = None
    rows_returned: int | None = None
    shared_blks_hit: int | None = None
    shared_blks_read: int | None = None


@dataclass
class PerformanceMetrics:
    """性能指标汇总"""

    database_info: dict[str, Any]
    connection_stats: ConnectionStats
    cache_efficiency: CacheEfficiency
    table_activity: list[TableActivity]
    index_usage: list[IndexUsage]
    lock_info: list[LockInfo]
    query_stats: list[QueryStats]
    collection_timestamp: datetime
    db_type: DatabaseType

    def to_dict(self) -> dict[str, Any]:
        """转换为字典"""
        return asdict(self)


# 主函数
class AsyncDatabasePerformanceCollector:
    """异步数据库性能收集器"""

    def __init__(self, session: AsyncSession, db_type: DatabaseType):
        """
        初始化收集器

        Args:
            session: SQLAlchemy异步会话
            db_type: 数据库类型
        """
        self.session: AsyncSession = session
        self.db_type: DatabaseType = db_type
        self.engine: AsyncEngine | AsyncConnection = session.bind

    async def _scalar(self, sql: str, default: Any = None) -> Any:
        """执行一条只取单值的查询，失败返回默认值。

        逐值查询而不是拼一条大 SELECT：MySQL 与 MariaDB 对别名的保留字判定
        不一致（``USER() AS current_user`` 在 MariaDB 上直接语法错误），
        一条挂掉就会让整个「数据库信息」变成空白。
        """
        try:
            result = await self.session.execute(text(sql))
            value = result.scalar()
        except Exception as e:
            logger.debug(f"查询失败 {sql!r}: {e}")
            return default
        return default if value is None else value

    async def _mysql_status(self, name: str) -> int | None:
        """取 ``SHOW GLOBAL STATUS`` 里的整数值。

        ``name`` 只允许来自本模块内的常量，不进用户输入。
        """
        try:
            result = await self.session.execute(
                text(f"SHOW GLOBAL STATUS LIKE '{name}'")
            )
            row = result.fetchone()
        except Exception as e:
            logger.debug(f"获取状态 {name} 失败: {e}")
            return None
        if row is None:
            return None
        try:
            return int(row[1])
        except (TypeError, ValueError):
            return None

    async def collect_performance_stats(self) -> PerformanceMetrics:
        """
        收集完整的性能统计信息

        Returns:
            PerformanceMetrics对象
        """
        try:
            db_info = await self._get_database_info()
            conn_stats = await self._get_connection_stats()
            cache_stats = await self._get_cache_efficiency()
            table_activity = await self._get_table_activity()
            index_usage = await self._get_index_usage()
            lock_info = await self._get_lock_info()
            query_stats = await self._get_query_stats()

            return PerformanceMetrics(
                database_info=db_info,
                connection_stats=conn_stats,
                cache_efficiency=cache_stats,
                table_activity=table_activity,
                index_usage=index_usage,
                lock_info=lock_info,
                query_stats=query_stats,
                collection_timestamp=datetime.now(),
                db_type=self.db_type,
            )

        except Exception as e:
            logger.error(f"收集性能统计信息失败: {e}")
            raise

    async def _get_database_info(self) -> dict[str, Any]:
        """获取数据库基本信息"""
        try:
            if self.db_type in ("mysql", "mariadb"):
                #  逐条查：两个方言对保留字与函数别名的容忍度不一样，
                #  合并成一条 SELECT 时 MariaDB 会因为 current_user 这个别名整条失败
                info = {
                    "version": await self._scalar("SELECT VERSION()"),
                    "database_name": await self._scalar("SELECT DATABASE()"),
                    "current_user": await self._scalar("SELECT CURRENT_USER()"),
                    "server_host": await self._scalar("SELECT @@hostname"),
                    "version_comment": await self._scalar("SELECT @@version_comment"),
                    "uptime_seconds": await self._mysql_status("Uptime"),
                    "data_dir": await self._scalar("SELECT @@datadir"),
                }
                return {key: value for key, value in info.items() if value is not None}

            elif self.db_type == "postgresql":
                result = await self.session.execute(
                    text(
                        "SELECT version(), current_database(), current_user, "
                        "inet_server_addr(), pg_postmaster_start_time()"
                    )
                )
                row = result.fetchone()
                if row:
                    return {
                        "version": row[0],
                        "database_name": row[1],
                        "current_user": row[2],
                        "server_ip": row[3],
                        "start_time": row[4],
                    }

            elif self.db_type == "sqlite":
                result = await self.session.execute(text("SELECT sqlite_version()"))
                version = result.scalar()
                return {
                    "version": version,
                    "database_name": "sqlite_db",
                    "current_user": "sqlite",
                    "server_ip": "embedded",
                }

            return {}

        except Exception as e:
            logger.warning(f"获取数据库信息失败: {e}")
            return {}

    async def _get_connection_stats(self) -> ConnectionStats:
        """获取连接统计"""
        try:
            if self.db_type in ("mysql", "mariadb"):
                # 获取最大连接数
                max_conn = None
                try:
                    result = await self.session.execute(
                        text("SHOW VARIABLES LIKE 'max_connections'")
                    )
                    var_row = result.fetchone()
                    max_conn = int(var_row.Value) if var_row else None
                except Exception as e:
                    logger.debug(f"获取 max_connections 失败: {e}")

                # 获取当前总连接数
                threads_connected = 0
                try:
                    result = await self.session.execute(
                        text("SHOW GLOBAL STATUS LIKE 'Threads_connected'")
                    )
                    row = result.fetchone()
                    threads_connected = int(row.Value) if row else 0
                except Exception as e:
                    logger.debug(f"获取 Threads_connected 失败: {e}")

                # 获取当前活跃连接数
                threads_running = 0
                try:
                    result = await self.session.execute(
                        text("SHOW GLOBAL STATUS LIKE 'Threads_running'")
                    )
                    row = result.fetchone()
                    threads_running = int(row.Value) if row else 0
                except Exception as e:
                    logger.debug(f"获取 Threads_running 失败: {e}")

                utilization = (threads_connected / max_conn * 100) if max_conn else None

                #  最长执行时间：PROCESSLIST 里非 Sleep 的会话，两个方言都支持
                longest = await self._scalar(
                    "SELECT MAX(TIME) FROM information_schema.PROCESSLIST "
                    "WHERE COMMAND <> 'Sleep'"
                )
                #  等待中的连接：8.0 用 data_lock_waits，5.7 与 MariaDB 用 INNODB_LOCK_WAITS
                waiting = await self._scalar(
                    "SELECT COUNT(*) FROM performance_schema.data_lock_waits"
                )
                if waiting is None:
                    waiting = await self._scalar(
                        "SELECT COUNT(*) FROM information_schema.INNODB_LOCK_WAITS"
                    )

                return ConnectionStats(
                    total_connections=threads_connected,
                    active_connections=threads_running,
                    idle_connections=max(0, threads_connected - threads_running),
                    max_allowed_connections=max_conn,
                    connection_utilization_percent=utilization,
                    longest_query_seconds=float(longest)
                    if longest is not None
                    else None,
                    waiting_connections=int(waiting) if waiting is not None else None,
                )

            elif self.db_type == "postgresql":
                result = await self.session.execute(
                    text("""
                    SELECT
                        COUNT(*) as total_connections,
                        COUNT(*) FILTER (WHERE state = 'active') as active_connections,
                        COUNT(*) FILTER (WHERE state = 'idle') as idle_connections,
                        COUNT(*) FILTER (WHERE state = 'idle in transaction') as idle_in_transaction,
                        MAX(EXTRACT(EPOCH FROM (now() - query_start))) as longest_query_seconds,
                        COUNT(*) FILTER (WHERE wait_event IS NOT NULL) as waiting_connections,
                        current_setting('max_connections')::int as max_connections
                    FROM pg_stat_activity
                    WHERE pid <> pg_backend_pid()
                """)
                )
                row = result.fetchone()
                if row:
                    total = row.total_connections
                    max_conn = row.max_connections
                    utilization = (total / max_conn * 100) if max_conn else None

                    return ConnectionStats(
                        total_connections=total,
                        active_connections=row.active_connections,
                        idle_connections=row.idle_connections,
                        max_allowed_connections=max_conn,
                        connection_utilization_percent=utilization,
                        longest_query_seconds=float(row.longest_query_seconds)
                        if row.longest_query_seconds
                        else None,
                        waiting_connections=row.waiting_connections,
                    )

            elif self.db_type == "sqlite":
                return ConnectionStats(
                    total_connections=1,
                    active_connections=1,
                    idle_connections=0,
                    max_allowed_connections=1,
                )

        except Exception as e:
            logger.warning(f"获取连接统计失败: {e}")

        return ConnectionStats()

    async def _get_cache_efficiency(self) -> CacheEfficiency:
        """获取缓存效率"""
        try:
            if self.db_type == "postgresql":
                result = await self.session.execute(
                    text("""
                    WITH cache_stats AS (
                        SELECT
                            sum(heap_blks_hit) as heap_hit,
                            sum(heap_blks_read) as heap_read,
                            sum(idx_blks_hit) as idx_hit,
                            sum(idx_blks_read) as idx_read
                        FROM pg_statio_user_tables
                    )
                    SELECT
                        CASE WHEN heap_hit + heap_read > 0
                            THEN heap_hit::float / (heap_hit + heap_read) * 100
                            ELSE 0 END as heap_hit_ratio,
                        CASE WHEN idx_hit + idx_read > 0
                            THEN idx_hit::float / (idx_hit + idx_read) * 100
                            ELSE 0 END as idx_hit_ratio,
                        heap_hit + idx_hit as logical_reads,
                        heap_read + idx_read as physical_reads
                    FROM cache_stats
                """)
                )
                row = result.fetchone()
                if row:
                    return CacheEfficiency(
                        heap_hit_ratio=float(row.heap_hit_ratio),
                        index_hit_ratio=float(row.idx_hit_ratio),
                        logical_reads=row.logical_reads,
                        physical_reads=row.physical_reads,
                    )

            elif self.db_type in ("mysql", "mariadb"):
                # 读请求次数
                read_requests = 0
                try:
                    result = await self.session.execute(
                        text(
                            "SHOW GLOBAL STATUS LIKE 'Innodb_buffer_pool_read_requests'"
                        )
                    )
                    row = result.fetchone()
                    read_requests = int(row.Value) if row else 0
                except Exception as e:
                    logger.debug(f"获取 Innodb_buffer_pool_read_requests 失败: {e}")

                # 实际物理读次数
                reads = 0
                try:
                    result = await self.session.execute(
                        text("SHOW GLOBAL STATUS LIKE 'Innodb_buffer_pool_reads'")
                    )
                    row = result.fetchone()
                    reads = int(row.Value) if row else 0
                except Exception as e:
                    logger.debug(f"获取 Innodb_buffer_pool_reads 失败: {e}")

                # 总页数
                pages_total = 0
                try:
                    result = await self.session.execute(
                        text("SHOW GLOBAL STATUS LIKE 'Innodb_buffer_pool_pages_total'")
                    )
                    row = result.fetchone()
                    pages_total = int(row.Value) if row else 0
                except Exception as e:
                    logger.debug(f"获取 Innodb_buffer_pool_pages_total 失败: {e}")

                # 空闲页数
                pages_free = 0
                try:
                    result = await self.session.execute(
                        text("SHOW GLOBAL STATUS LIKE 'Innodb_buffer_pool_pages_free'")
                    )
                    row = result.fetchone()
                    pages_free = int(row.Value) if row else 0
                except Exception as e:
                    logger.debug(f"获取 Innodb_buffer_pool_pages_free 失败: {e}")

                # Buffer Pool 总大小（字节）
                pool_size_bytes = None
                try:
                    result = await self.session.execute(
                        text("SELECT @@innodb_buffer_pool_size as pool_size")
                    )
                    row = result.fetchone()
                    pool_size_bytes = int(row.pool_size) if row else None
                except Exception as e:
                    logger.debug(f"获取 innodb_buffer_pool_size 失败: {e}")

                #  计数器可能被 stats 重置：reads > requests 时比值会变成负数，
                #  夹到 [0, 100] 才是个能看的命中率
                #  计数器可能被 stats 重置：reads > requests 时比值没有意义，
                #  返回 None 由前端隐藏，而不是显示成 0% 吓人
                hit_ratio = (
                    max(0.0, min(100.0, (1 - reads / read_requests) * 100))
                    if read_requests > 0 and reads <= read_requests
                    else None
                )
                #  MyISAM 的 key buffer 命中率是 MySQL 侧唯一现成的「索引缓存」指标；
                #  InnoDB 没有这个概念，此时保持 None 而不是编一个值出来
                key_requests = await self._mysql_status("Key_read_requests") or 0
                key_reads = await self._mysql_status("Key_reads") or 0
                key_hit_ratio = (
                    (1 - key_reads / key_requests) * 100 if key_requests > 0 else None
                )
                cache_used = (
                    (1 - pages_free / pages_total) * 100 if pages_total > 0 else None
                )

                return CacheEfficiency(
                    buffer_pool_hit_ratio=hit_ratio,
                    index_hit_ratio=key_hit_ratio,
                    logical_reads=read_requests,
                    physical_reads=reads,
                    cache_size_mb=pool_size_bytes / (1024 * 1024)
                    if pool_size_bytes
                    else None,
                    cache_used_percent=cache_used,
                )

            elif self.db_type == "sqlite":
                # 获取缓存设置：PRAGMA cache_size 返回正数表示页数，负数表示 KiB 数
                cache_val = None
                page_size = None
                try:
                    result = await self.session.execute(text("PRAGMA cache_size"))
                    cache_val = result.scalar()
                except Exception as e:
                    logger.debug(f"获取 PRAGMA cache_size 失败: {e}")

                try:
                    result = await self.session.execute(text("PRAGMA page_size"))
                    page_size = result.scalar()
                except Exception as e:
                    logger.debug(f"获取 PRAGMA page_size 失败: {e}")

                cache_size_mb = None
                if cache_val is not None and page_size:
                    if cache_val > 0:
                        # 正数：页数
                        cache_size_bytes = cache_val * page_size
                    else:
                        # 负数：KiB 数，取绝对值
                        cache_size_bytes = (-cache_val) * 1024
                    cache_size_mb = cache_size_bytes / (1024 * 1024)

                return CacheEfficiency(cache_size_mb=cache_size_mb)

        except Exception as e:
            logger.warning(f"获取缓存效率失败: {e}")

        return CacheEfficiency()

    async def _get_table_activity(self) -> list[TableActivity]:
        """获取表活动统计"""
        tables: list[TableActivity] = []

        try:
            if self.db_type == "postgresql":
                result = await self.session.execute(
                    text("""
                    SELECT
                        schemaname,
                        relname,
                        seq_scan,
                        seq_tup_read,
                        n_tup_ins,
                        n_tup_upd,
                        n_tup_del,
                        n_live_tup,
                        n_dead_tup,
                        pg_total_relation_size(quote_ident(schemaname) || '.' || quote_ident(relname)) as total_bytes,
                        pg_indexes_size(quote_ident(schemaname) || '.' || quote_ident(relname)) as index_bytes,
                        last_vacuum,
                        last_analyze
                    FROM pg_stat_user_tables
                    ORDER BY seq_scan DESC
                    LIMIT 20
                """)
                )

                for row in result:
                    total_mb = (
                        row.total_bytes / (1024 * 1024) if row.total_bytes else None
                    )
                    index_mb = (
                        row.index_bytes / (1024 * 1024) if row.index_bytes else None
                    )

                    tables.append(
                        TableActivity(
                            table_name=row.relname,
                            schema_name=row.schemaname,
                            full_scans=row.seq_scan,
                            rows_scanned=row.seq_tup_read,
                            rows_inserted=row.n_tup_ins,
                            rows_updated=row.n_tup_upd,
                            rows_deleted=row.n_tup_del,
                            live_rows=row.n_live_tup,
                            dead_rows=row.n_dead_tup,
                            total_size_mb=total_mb,
                            index_size_mb=index_mb,
                            last_vacuum=row.last_vacuum,
                            last_analyze=row.last_analyze,
                        )
                    )

            elif self.db_type in ("mysql", "mariadb"):
                # 获取当前数据库名（可能为 NULL）
                db_result = await self.session.execute(text("SELECT DATABASE()"))
                db_name = db_result.scalar()

                # 构建查询条件：如果 db_name 为 NULL，则查询所有非系统库的表；否则只查询该库
                if db_name:
                    condition = "TABLE_SCHEMA = :db_name"
                    params = {"db_name": db_name}
                else:
                    condition = "TABLE_SCHEMA NOT IN ('mysql', 'performance_schema', 'information_schema')"
                    params = {}

                query = f"""
                    SELECT
                        TABLE_SCHEMA,
                        TABLE_NAME,
                        TABLE_ROWS,
                        DATA_LENGTH,
                        INDEX_LENGTH,
                        DATA_FREE,
                        (DATA_LENGTH + INDEX_LENGTH) / 1024 / 1024 AS total_size_mb,
                        INDEX_LENGTH / 1024 / 1024 AS index_size_mb
                    FROM information_schema.TABLES
                    WHERE {condition}
                    ORDER BY total_size_mb DESC
                    LIMIT 20
                """
                result = await self.session.execute(text(query), params)

                tables = [
                    TableActivity(
                        table_name=row.TABLE_NAME,
                        schema_name=row.TABLE_SCHEMA,
                        live_rows=row.TABLE_ROWS,
                        total_size_mb=float(row.total_size_mb)
                        if row.total_size_mb
                        else None,
                        index_size_mb=float(row.index_size_mb)
                        if row.index_size_mb
                        else None,
                        # 其他统计字段无法从 information_schema.TABLES 获取，保持 None
                    )
                    for row in result
                ]

            elif self.db_type == "sqlite":
                # 获取所有用户表名
                result = await self.session.execute(
                    text(
                        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
                    )
                )
                table_names = [row[0] for row in result.fetchall()]

                for table_name in table_names[:20]:  # 限制前20个表
                    # 获取行数（注意：COUNT(*) 可能对大表有性能影响）
                    try:
                        count_result = await self.session.execute(
                            text(f'SELECT COUNT(*) FROM "{table_name}"')
                        )
                        row_count = count_result.scalar()
                    except Exception as e:
                        logger.debug(f"获取表 {table_name} 行数失败: {e}")
                        row_count = None

                    tables.append(
                        TableActivity(
                            table_name=table_name,
                            live_rows=row_count,
                        )
                    )

        except Exception as e:
            logger.warning(f"获取表活动统计失败: {e}")

        return tables

    async def _get_index_usage(self) -> list[IndexUsage]:
        """获取索引使用情况"""
        indexes: list[IndexUsage] = []

        try:
            if self.db_type == "postgresql":
                result = await self.session.execute(
                    text("""
                    SELECT
                        schemaname,
                        tablename,
                        indexname,
                        idx_scan,
                        idx_tup_read,
                        idx_tup_fetch,
                        pg_relation_size(quote_ident(schemaname) || '.' || quote_ident(indexname)) as index_size
                    FROM pg_stat_user_indexes
                    ORDER BY idx_scan ASC
                    LIMIT 20
                """)
                )

                for row in result:
                    size_mb = row.index_size / (1024 * 1024) if row.index_size else None

                    indexes.append(
                        IndexUsage(
                            index_name=row.indexname,
                            table_name=row.tablename,
                            schema_name=row.schemaname,
                            scan_count=row.idx_scan,
                            rows_fetched=row.idx_tup_fetch,
                            size_mb=size_mb,
                        )
                    )

            elif self.db_type in ("mysql", "mariadb"):
                # 获取当前数据库名
                db_result = await self.session.execute(text("SELECT DATABASE()"))
                db_name = db_result.scalar()

                if db_name:
                    condition = "TABLE_SCHEMA = :db_name"
                    params = {"db_name": db_name}
                else:
                    condition = "TABLE_SCHEMA NOT IN ('mysql', 'performance_schema', 'information_schema')"
                    params = {}

                query = f"""
                    SELECT
                        TABLE_SCHEMA,
                        TABLE_NAME,
                        INDEX_NAME,
                        NON_UNIQUE,
                        CARDINALITY,
                        INDEX_TYPE
                    FROM information_schema.STATISTICS
                    WHERE {condition}
                    ORDER BY TABLE_SCHEMA, TABLE_NAME, INDEX_NAME
                    LIMIT 50
                """
                result = await self.session.execute(text(query), params)

                #  performance_schema 有真实的使用计数，但不是每个实例都开着；
                #  取不到就保持 None，别用一个 0 假装「没被用过」
                usage: dict[tuple[str, str, str], tuple[int | None, int | None]] = {}
                try:
                    usage_result = await self.session.execute(
                        text("""
                        SELECT OBJECT_SCHEMA, OBJECT_NAME, INDEX_NAME,
                               COUNT_STAR, COUNT_READ
                        FROM performance_schema.table_io_waits_summary_by_index_usage
                        WHERE OBJECT_SCHEMA = DATABASE()
                        """)
                    )
                    for urow in usage_result:
                        usage[(urow[0], urow[1], urow[2])] = (urow[3], urow[4])
                except Exception as e:
                    logger.debug(f"performance_schema 索引统计不可用: {e}")

                # 按索引名分组，获取每个索引的信息（去重，同一索引可能有多行对应多列）
                seen = set()
                for row in result:
                    key = (row.TABLE_SCHEMA, row.TABLE_NAME, row.INDEX_NAME)
                    if key in seen:
                        continue
                    seen.add(key)
                    scans, reads_rows = usage.get(key, (None, None))
                    indexes.append(
                        IndexUsage(
                            index_name=row.INDEX_NAME,
                            table_name=row.TABLE_NAME,
                            schema_name=row.TABLE_SCHEMA,
                            scan_count=scans,
                            rows_fetched=reads_rows,
                            cardinality=row.CARDINALITY,
                            unique=(row.NON_UNIQUE == 0),
                        )
                    )

            elif self.db_type == "sqlite":
                result = await self.session.execute(
                    text(
                        "SELECT name, tbl_name, sql FROM sqlite_master WHERE type = 'index'"
                    )
                )

                indexes = [
                    IndexUsage(
                        index_name=row.name,
                        table_name=row.tbl_name,
                        definition=row.sql,
                    )
                    for row in result
                ]
        except Exception as e:
            logger.warning(f"获取索引使用情况失败: {e}")

        return indexes

    async def _get_lock_info(self) -> list[LockInfo]:
        """获取锁信息"""
        locks: list[LockInfo] = []

        try:
            if self.db_type == "postgresql":
                result = await self.session.execute(
                    text("""
                    SELECT
                        locktype,
                        mode,
                        COUNT(*) as lock_count,
                        COUNT(*) FILTER (WHERE granted = false) as waiting_count,
                        ARRAY_AGG(DISTINCT pid) as pids
                    FROM pg_locks
                    WHERE pid <> pg_backend_pid()
                    GROUP BY locktype, mode
                    HAVING COUNT(*) > 0
                    ORDER BY lock_count DESC
                """)
                )

                for row in result:
                    # 获取被阻塞的查询（如果有等待的锁）
                    blocked_queries = []
                    if row.waiting_count and row.waiting_count > 0:
                        query_result = await self.session.execute(
                            text("""
                            SELECT query FROM pg_stat_activity
                            WHERE pid = ANY(:pids) AND wait_event_type = 'Lock'
                        """),
                            {"pids": list(row.pids) if row.pids else []},
                        )
                        blocked_queries = [q[0] for q in query_result.fetchall()]

                    locks.append(
                        LockInfo(
                            lock_type=row.locktype,
                            lock_mode=row.mode,
                            lock_count=row.lock_count,
                            waiting_count=row.waiting_count,
                            blocked_pids=list(row.pids) if row.pids else None,
                            blocked_queries=blocked_queries
                            if blocked_queries
                            else None,
                        )
                    )

            elif self.db_type in ("mysql", "mariadb"):
                # 使用InnoDB锁信息
                try:
                    result = await self.session.execute(
                        text("""
                        SELECT
                            r.trx_id AS waiting_trx_id,
                            r.trx_mysql_thread_id AS waiting_thread,
                            r.trx_query AS waiting_query,
                            b.trx_id AS blocking_trx_id,
                            b.trx_mysql_thread_id AS blocking_thread,
                            b.trx_query AS blocking_query
                        FROM information_schema.INNODB_LOCK_WAITS w
                        INNER JOIN information_schema.INNODB_TRX b ON b.trx_id = w.blocking_trx_id
                        INNER JOIN information_schema.INNODB_TRX r ON r.trx_id = w.requesting_trx_id
                    """)
                    )

                    # 按锁类型分组
                    lock_groups: dict[str, LockInfo] = {}

                    for row in result:
                        lock_key = f"waiting:{row.waiting_trx_id}:blocking:{row.blocking_trx_id}"

                        if lock_key not in lock_groups:
                            lock_groups[lock_key] = LockInfo(
                                lock_type="row_lock",  # InnoDB主要是行锁
                                lock_mode="exclusive",  # 阻塞的锁通常是排他锁
                                lock_count=1,
                                waiting_count=1,
                                blocked_pids=[row.waiting_thread],
                                blocked_queries=[row.waiting_query],
                            )
                        else:
                            lock_groups[lock_key].lock_count += 1

                    locks = list(lock_groups.values())
                except Exception as e:
                    logger.debug(f"获取InnoDB锁信息失败: {e}")

            # SQLite 锁信息可以通过 PRAGMA lock_status 获取，但输出复杂，暂不实现

        except Exception as e:
            logger.warning(f"获取锁信息失败: {e}")

        return locks

    async def _get_query_stats(self) -> list[QueryStats]:
        """获取查询统计"""
        queries: list[QueryStats] = []

        try:
            if self.db_type == "postgresql":
                # 检查pg_stat_statements扩展是否启用
                result = await self.session.execute(
                    text(
                        "SELECT COUNT(*) FROM pg_extension WHERE extname = 'pg_stat_statements'"
                    )
                )
                extension_exists = (result.scalar() or 0) > 0

                if extension_exists:
                    result = await self.session.execute(
                        text("""
                        SELECT
                            queryid,
                            query,
                            calls,
                            total_exec_time,
                            mean_exec_time,
                            min_exec_time,
                            max_exec_time,
                            rows,
                            shared_blks_hit,
                            shared_blks_read
                        FROM pg_stat_statements
                        ORDER BY total_exec_time DESC
                        LIMIT 10
                    """)
                    )
                    queries = [
                        QueryStats(
                            query_hash=str(row.queryid),
                            query_text=row.query[:500]
                            if row.query
                            else None,  # 截断长查询
                            total_executions=row.calls,
                            total_time_ms=row.total_exec_time,
                            avg_time_ms=row.mean_exec_time,
                            min_time_ms=row.min_exec_time,
                            max_time_ms=row.max_exec_time,
                            rows_returned=row.rows,
                            shared_blks_hit=row.shared_blks_hit,
                            shared_blks_read=row.shared_blks_read,
                        )
                        for row in result
                    ]

            elif self.db_type in ("mysql", "mariadb"):
                # 优先尝试 performance_schema 获取详细统计
                try:
                    result = await self.session.execute(
                        text("""
                        SELECT
                            DIGEST_TEXT,
                            COUNT_STAR,
                            -- performance_schema 的计时单位是皮秒，/1e9 直接得到毫秒
                            SUM_TIMER_WAIT / 1000000000 as total_time_ms,
                            AVG_TIMER_WAIT / 1000000000 as avg_time_ms,
                            SUM_ROWS_SENT
                        FROM performance_schema.events_statements_summary_by_digest
                        WHERE DIGEST_TEXT IS NOT NULL
                        ORDER BY SUM_TIMER_WAIT DESC
                        LIMIT 10
                    """)
                    )
                    rows = result.fetchall()
                    if rows:
                        for row in rows:
                            queries.append(
                                QueryStats(
                                    query_text=row.DIGEST_TEXT[:500]
                                    if row.DIGEST_TEXT
                                    else None,
                                    total_executions=row.COUNT_STAR,
                                    total_time_ms=float(row.total_time_ms)
                                    if row.total_time_ms is not None
                                    else None,
                                    avg_time_ms=float(row.avg_time_ms)
                                    if row.avg_time_ms is not None
                                    else None,
                                    rows_returned=row.SUM_ROWS_SENT,
                                )
                            )
                        return queries
                except Exception as e:
                    logger.debug(f"performance_schema 查询失败，降级到慢查询统计: {e}")

                # 降级：获取慢查询总数
                try:
                    result = await self.session.execute(
                        text("SHOW GLOBAL STATUS LIKE 'Slow_queries'")
                    )
                    slow_row = result.fetchone()
                    if slow_row and int(slow_row.Value) > 0:
                        queries.append(
                            QueryStats(
                                query_text="慢查询统计（仅总数）",
                                total_executions=int(slow_row.Value),
                            )
                        )
                except Exception as e:
                    logger.debug(f"获取慢查询统计失败: {e}")

            # SQLite 没有查询统计，直接返回空列表

        except Exception as e:
            logger.warning(f"获取查询统计失败: {e}")

        return queries


# 使用示例
async def collect_database_performance(
    session: AsyncSession, db_type: DatabaseType
) -> PerformanceMetrics:
    """
    主函数：收集数据库性能统计

    Args:
        session: SQLAlchemy异步会话
        db_type: 数据库类型

    Returns:
        PerformanceMetrics对象
    """
    collector = AsyncDatabasePerformanceCollector(session, db_type)
    return await collector.collect_performance_stats()
