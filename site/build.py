"""公開静的サイトを生成する CLI。

DB から講座・分類を読み、出力ディレクトリに一式を書き出す。
使い方: .venv/bin/python site/build.py --out dist
設定は環境変数(SEMINAR_SITE_BASE_URL / SEMINAR_SUBMIT_ADDR / SEMINAR_DB_URL)。
"""

import argparse

from app.core.config import get_settings
from app.core.db import get_sessionmaker
from app.models import Category, Course
from app.services.sitegen import build_site
from sqlalchemy import select


def main() -> None:
    ap = argparse.ArgumentParser(description="公開静的サイトの生成")
    ap.add_argument("--out", default="dist", help="出力ディレクトリ(既定: dist)")
    args = ap.parse_args()

    cfg = get_settings()
    with get_sessionmaker()() as session:
        courses = session.scalars(select(Course)).all()
        categories = session.scalars(select(Category)).all()
    build_site(
        courses,
        categories,
        args.out,
        base_url=cfg.site_base_url,
        submit_addr=cfg.submit_addr,
        api_base=cfg.api_base_url,
    )
    print(f"生成完了: {args.out}/")


if __name__ == "__main__":
    main()
