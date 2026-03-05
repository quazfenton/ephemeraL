"""Centralized configuration management using Pydantic settings."""

from pydantic import Field
from pydantic_settings import BaseSettings
from typing import Optional, List


class Settings(BaseSettings):
    """
    Centralized application configuration loaded from environment variables.
    
    All settings can be overridden via environment variables or a .env file.
    """
    
    # =========================================================================
    # Identity & Authentication
    # =========================================================================
    
    jwt_public_key: str = Field(
        default="",
        env="JWT_PUBLIC_KEY",
        description="RSA public key for JWT verification (PEM format)",
    )
    jwt_audience: Optional[str] = Field(
        default=None,
        env="JWT_AUDIENCE",
        description="Expected JWT audience claim",
    )
    jwt_issuer: Optional[str] = Field(
        default=None,
        env="JWT_ISSUER",
        description="Expected JWT issuer claim",
    )
    jwt_algorithm: str = Field(
        default="RS256",
        env="JWT_ALGORITHM",
        description="JWT signing algorithm",
    )
    
    # =========================================================================
    # Sandbox Configuration
    # =========================================================================
    
    sandbox_root: str = Field(
        default="/tmp/sandboxes",
        env="SANDBOX_ROOT",
        description="Root directory for sandbox workspaces",
    )
    default_timeout: int = Field(
        default=15,
        env="DEFAULT_TIMEOUT",
        description="Default command execution timeout in seconds",
    )
    max_file_read_size: int = Field(
        default=10 * 1024 * 1024,
        env="MAX_FILE_READ_SIZE",
        description="Maximum file size in bytes allowed for read_file API",
    )
    allowed_commands: List[str] = Field(
        default=["python", "node"],
        env="ALLOWED_COMMANDS",
        description="Comma-separated list of allowed commands",
    )
    
    # =========================================================================
    # Resource Quotas
    # =========================================================================
    
    quota_executions_per_hour: int = Field(
        default=120,
        env="QUOTA_EXECUTIONS_PER_HOUR",
        description="Maximum command executions per sandbox per hour",
    )
    quota_max_memory_mb: int = Field(
        default=2048,
        env="QUOTA_MAX_MEMORY_MB",
        description="Maximum memory allocation per sandbox in MB",
    )
    quota_max_concurrent: int = Field(
        default=10,
        env="QUOTA_MAX_CONCURRENT",
        description="Maximum concurrent sandboxes per user",
    )
    quota_max_storage_bytes: int = Field(
        default=5 * 1024 * 1024 * 1024,  # 5GB
        env="QUOTA_MAX_STORAGE_BYTES",
        description="Maximum storage per sandbox in bytes",
    )
    quota_max_cpu_seconds_per_hour: int = Field(
        default=3600,
        env="QUOTA_MAX_CPU_SECONDS_PER_HOUR",
        description="Maximum CPU time per sandbox per hour",
    )
    quota_max_network_egress_bytes_per_hour: int = Field(
        default=1024 * 1024 * 1024,  # 1GB
        env="QUOTA_MAX_NETWORK_EGRESS_BYTES_PER_HOUR",
        description="Maximum network egress per sandbox per hour",
    )
    
    # =========================================================================
    # Storage Backend
    # =========================================================================
    
    storage_backend: str = Field(
        default="auto",
        env="STORAGE_BACKEND",
        description="Storage backend: 'auto', 's3', or 'local'",
    )
    s3_endpoint: Optional[str] = Field(
        default=None,
        env="S3_ENDPOINT",
        description="S3-compatible storage endpoint URL",
    )
    s3_access_key: str = Field(
        default="",
        env="S3_ACCESS_KEY",
        description="S3 access key",
    )
    s3_secret_key: str = Field(
        default="",
        env="S3_SECRET_KEY",
        description="S3 secret key",
    )
    s3_bucket: str = Field(
        default="ephemeral-snapshots",
        env="S3_BUCKET",
        description="S3 bucket name for snapshots",
    )
    s3_region: str = Field(
        default="us-east-1",
        env="S3_REGION",
        description="S3 region",
    )
    local_storage_dir: str = Field(
        default="/tmp/ephemeral-storage",
        env="LOCAL_STORAGE_DIR",
        description="Local directory for snapshot storage",
    )
    
    # =========================================================================
    # Preview Router
    # =========================================================================
    
    preview_router_url: str = Field(
        default="http://127.0.0.1:8001",
        env="PREVIEW_ROUTER_URL",
        description="URL of the preview router service",
    )
    
    # =========================================================================
    # Rate Limiting
    # =========================================================================
    
    rate_limit_per_minute: int = Field(
        default=60,
        env="RATE_LIMIT_PER_MINUTE",
        description="Maximum requests per minute per client",
    )
    rate_limit_burst: int = Field(
        default=10,
        env="RATE_LIMIT_BURST",
        description="Maximum requests per second (burst limit)",
    )
    
    # =========================================================================
    # Tool Integrations
    # =========================================================================
    
    composio_api_key: Optional[str] = Field(
        default=None,
        env="COMPOSIO_API_KEY",
        description="Composio API key for tool integrations",
    )
    
    # =========================================================================
    # Observability
    # =========================================================================
    
    log_level: str = Field(
        default="INFO",
        env="LOG_LEVEL",
        description="Logging level (DEBUG, INFO, WARNING, ERROR)",
    )
    log_format: str = Field(
        default="console",
        env="LOG_FORMAT",
        description="Logging format: 'console' or 'json'",
    )
    otlp_endpoint: Optional[str] = Field(
        default=None,
        env="OTLP_ENDPOINT",
        description="OpenTelemetry OTLP endpoint for distributed tracing",
    )
    enable_metrics: bool = Field(
        default=True,
        env="ENABLE_METRICS",
        description="Enable Prometheus metrics endpoint",
    )
    
    # =========================================================================
    # API Configuration
    # =========================================================================
    
    api_host: str = Field(
        default="0.0.0.0",
        env="API_HOST",
        description="API server host",
    )
    api_port: int = Field(
        default=8000,
        env="API_PORT",
        description="API server port",
    )
    sandbox_api_url: str = Field(
        default="http://127.0.0.1:8000",
        env="SANDBOX_API_URL",
        description="URL of the sandbox API service",
    )
    snapshot_api_url: str = Field(
        default="http://127.0.0.1:8002",
        env="SNAPSHOT_API_URL",
        description="URL of the snapshot API service",
    )
    agent_api_url: str = Field(
        default="http://127.0.0.1:8003",
        env="AGENT_API_URL",
        description="URL of the agent API service",
    )
    
    # =========================================================================
    # Workspace Directories
    # =========================================================================
    
    workspace_base_dir: str = Field(
        default="/srv/workspaces",
        env="WORKSPACE_BASE_DIR",
        description="Base directory for user workspaces",
    )
    snapshot_base_dir: str = Field(
        default="/srv/snapshots",
        env="SNAPSHOT_BASE_DIR",
        description="Base directory for snapshot storage",
    )
    
    # =========================================================================
    # Snapshot Configuration
    # =========================================================================
    
    snapshot_retention_count: int = Field(
        default=5,
        env="SNAPSHOT_RETENTION_COUNT",
        description="Number of snapshots to retain per user",
    )
    snapshot_on_idle: bool = Field(
        default=True,
        env="SNAPSHOT_ON_IDLE",
        description="Create snapshot when sandbox becomes idle",
    )
    snapshot_on_save: bool = Field(
        default=True,
        env="SNAPSHOT_ON_SAVE",
        description="Create snapshot on explicit save request",
    )
    snapshot_daily: bool = Field(
        default=False,
        env="SNAPSHOT_DAILY",
        description="Create daily snapshots",
    )
    
    # =========================================================================
    # Container Configuration
    # =========================================================================
    
    container_image: str = Field(
        default="ubuntu:22.04",
        env="CONTAINER_IMAGE",
        description="Default container image for sandboxes",
    )
    container_prefix: str = Field(
        default="shell-",
        env="CONTAINER_PREFIX",
        description="Prefix for container names",
    )
    container_runtime: str = Field(
        default="auto",
        env="CONTAINER_RUNTIME",
        description="Container runtime: 'auto', 'firecracker', or 'process'",
    )
    
    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        case_sensitive = False
        extra = "ignore"  # Ignore extra fields not defined in the model


# Global settings instance (singleton)
_settings: Optional[Settings] = None


def get_settings() -> Settings:
    """
    Get the global settings instance, creating it if necessary.
    
    Returns:
        Settings: The global configuration instance.
    """
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings


# Convenience access to settings
settings = get_settings()
