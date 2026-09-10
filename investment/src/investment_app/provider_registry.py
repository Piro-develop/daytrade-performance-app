"""Explicit provider availability; desktop integrations never start from the web UI."""
from dataclasses import dataclass
from .models import InputError

@dataclass(frozen=True)
class ProviderRegistration:
    key: str
    label: str
    environment: str
    implemented: bool

PROVIDERS = (
    ProviderRegistration("stooq", "無料公開日足", "portable", True),
    ProviderRegistration("public_context", "ECB・Fed公開情報", "portable", True),
    ProviderRegistration("csv", "ブラウザCSVアップロード", "portable", True),
    ProviderRegistration("screenshot", "画像アップロード・目視確認", "portable", True),
    ProviderRegistration("hyper_sbi2", "HYPER SBI 2 デスクトップ接続", "windows_local", False),
    ProviderRegistration("tradingview", "TradingView専用接続", "portable", False),
    ProviderRegistration("kabu_station", "kabuステーションAPI", "windows_local", False),
    ProviderRegistration("jquants", "J-Quants API", "portable", False),
)

def require_available(key, environment="portable"):
    provider=next((p for p in PROVIDERS if p.key==key),None)
    if provider is None or not provider.implemented:
        raise InputError("このProviderは未接続です。無料公開データ・CSV・画像で補完してください。")
    if provider.environment=="windows_local" and environment!="windows_local":
        raise InputError("Windows専用経路はクラウド側から起動できません。")
    return provider
