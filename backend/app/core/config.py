"""設定。環境変数(SEMINAR_ プレフィックス)または .env で上書きする。"""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="SEMINAR_", env_file=".env")

    db_url: str = "postgresql+psycopg://localhost/seminar"
    site_base_url: str = "https://kensyu.example.jp"  # 公開サイト(QRの宛先)
    submit_addr: str = "moshikomi@example.jp"  # 申込専用メールアドレス
    # 採番方式: seq(通し連番)/ fy(年度リセット)/ fy-cat(年度-分類-何回目)。
    # 規模に合わせて選ぶ(services/no.py)
    no_style: str = "seq"

    # 送信(段階1: 機関の既存 SMTP リレー。段階2で自営 Stalwart へ)
    smtp_host: str = "localhost"
    smtp_port: int = 25
    smtp_user: str = ""  # 空なら認証なし
    smtp_pass: str = ""
    smtp_starttls: bool = False
    mail_from_name: str = "研修・セミナー事務局"

    # 受信(申込専用アドレスの IMAP。フォルダ=未処理キューの状態)
    imap_host: str = "localhost"
    imap_port: int = 993
    imap_user: str = ""
    imap_pass: str = ""
    imap_done: str = "done"  # 処理済みフォルダ
    imap_pending: str = "pending"  # 未処理フォルダ(事務局アプリが見る)
    imap_returned: str = "returned"  # 差戻し済みフォルダ
    imap_poll_sec: int = 180

    received_dir: str = "received"  # 申込原本(xlsx / eml)の保存先
    output_dir: str = "output"  # 名簿・台帳などの帳票出力先
    site_out: str = "dist"  # 静的サイトの出力先
    jitsi_base: str = "https://meet.example.jp"  # 自営 Jitsi(配信URL自動生成)

    # 公開 API(Cloudflare 経由。apply ページが fetch する絶対 URL)
    api_base_url: str = "https://api.example.jp/api/v1"
    # OnlyOffice Docs(Document Server)。JWT 必須(空は開発時のみ)
    onlyoffice_url: str = "https://api.example.jp/onlyoffice"
    onlyoffice_jwt_secret: str = ""


@lru_cache
def get_settings() -> Settings:
    return Settings()
