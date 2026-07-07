"""公開静的サイトの生成。

courses・categories(モデルのリスト)から出力ディレクトリを組み立てる
純粋な処理。DB からの読み出しは site/build.py(CLI)や事務局アプリが行う。
個人情報・meeting_url・**申込様式 xlsx・申込アドレス**は出力に一切含めない
(様式と宛先は受領メール・印刷物・電話で個別に渡す。ボット収集対策)。
テンプレートは site/templates/。
"""

import shutil
from collections.abc import Iterable
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from app.models import Category, Course
from app.services import forms, qr

ROOT = Path(__file__).resolve().parents[3]
TEMPLATES = ROOT / "site" / "templates"
STATIC = ROOT / "site" / "static"


def build_site(
    courses: Iterable[Course],
    categories: Iterable[Category],
    outdir: str | Path,
    *,
    base_url: str,
    contact_note: str,
    api_base: str = "/api/v1",
) -> None:
    """静的サイト一式を outdir に生成する(draft は一切出力しない)。"""
    out = Path(outdir)
    env = Environment(
        loader=FileSystemLoader(TEMPLATES), autoescape=select_autoescape()
    )
    env.filters["jst"] = forms.jst

    courses = list(courses)
    categories = sorted(categories, key=lambda c: c.sort_order)
    cat_name = {c.id: c.name for c in categories}

    listed = [c for c in courses if c.status in ("open", "closed")]
    groups = []
    for cat in categories:
        mine = [c for c in listed if c.category_id == cat.id]
        mine.sort(key=lambda c: (c.status != "open", c.starts_at))  # 募集中を上に
        if mine:
            groups.append((cat, mine))
    finished = sorted(
        (c for c in courses if c.status == "finished"),
        key=lambda c: c.starts_at,
        reverse=True,
    )

    out.mkdir(parents=True, exist_ok=True)
    (out / "static").mkdir(exist_ok=True)
    for f in STATIC.iterdir():
        shutil.copy(f, out / "static" / f.name)

    def render(template: str, dest: str | Path, **ctx) -> None:
        path = out / dest
        path.parent.mkdir(parents=True, exist_ok=True)
        html = env.get_template(template).render(
            base_url=base_url,
            contact_note=contact_note,
            api_base=api_base,
            cat_name=cat_name,
            **ctx,
        )
        path.write_text(html, encoding="utf-8")

    render("index.html", "index.html", groups=groups)
    render("archive.html", "archive.html", finished=finished)
    render("apply.html", Path("apply") / "index.html")  # ブラウザ記入(経路1)

    for course in listed + finished:
        cdir = Path("courses") / str(course.id)
        (out / cdir).mkdir(parents=True, exist_ok=True)

        flyer = None
        if course.flyer_path and Path(course.flyer_path).exists():
            shutil.copy(course.flyer_path, out / cdir / "flyer.pdf")
            flyer = "flyer.pdf"

        (out / cdir / "qr.png").write_bytes(qr.png(f"{base_url}/courses/{course.id}/"))

        render(
            "course.html",
            cdir / "index.html",
            c=course,
            locs=forms.loc_labels(course),
            flyer=flyer,
        )
