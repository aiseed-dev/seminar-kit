# DESIGN.md — 実装設計(seminar)

仕様の正は `docs/` と `db/schema.sql`。本書は「どの順で・どう作るか」の設計であり、
仕様の追加・変更はしない。仕様に無い判断は下部「確認事項」に集めた(CLAUDE.md の指示どおり
推測で進めない)。

## 方針

- **様式 xlsx が唯一のフォーム定義**なので、実装の心臓部は
  「様式の生成(forms)と読み取り(パーサ)」。ここを最初に固め、
  ラウンドトリップテスト(生成した様式に記入→読み取り→元データと一致)で守る
- 3経路(ブラウザ記入/メール添付/簡易メール)は入口が違うだけで
  同一パーサ・同一登録処理に合流する。合流点(services)を先に作り、入口は後から足す
- 外部依存(IMAP/SMTP・OnlyOffice・PocketBase・Jitsi)はすべて抽象の裏に置き、
  開発時はフェイクで動かす。実環境の結線は導入フェーズの作業とする

## リポジトリ構成(CLAUDE.md の指定どおり)

```
backend/
  app/
    core/       設定(pydantic-settings)・DB(SQLAlchemy 2.0)・定数
    models/     schema.sql と1:1(staff, categories, courses, companies,
                applications, attendees, mails)
    schemas/    Pydantic v2(公開APIの入出力のみ)
    routers/    courses, docs, qr(公開APIはこの3つで全部)
    services/   no.py(採番) forms.py(様式生成) parse.py(様式読取)
                regist.py(登録=companies upsert+採番+受領メール起動)
                mail.py(送信抽象) mailin.py(IMAP監視・判別)
                roster.py(名簿xlsx) ledger.py(台帳xlsx) sitegen.py(静的再生成)
                qr.py(segno)
  tests/
site/           生成器(Python)+テンプレート+ブラウザ記入ページ(静的1枚)
office/         Flet。backend の models/services を import
db/schema.sql   正(既存)
deploy/         systemd unit・Caddyfile・手順書(後半フェーズ)
```

命名: 手で打つ名前は短く、複数語はハイフン。Python モジュールのみ小文字短名。

## データフロー(合流の設計)

```
経路1 OnlyOffice callback ─┐
経路2 IMAP添付xlsx ────────┼→ parse.py(名前付きセル・版判定・検証)
経路3 簡易メール本文 ──────┘      │成功                │失敗
                            regist.py            IMAP「未処理」フォルダへ移動
                    (companies upsert・採番・    (原文ごと残る。黙って捨てない。
                     applications+attendees・     修正依頼の自動返信を送付)
                     received_file保存)
                            │
                        mail.py 受領メール(申込番号つき)

未処理キュー = IMAP フォルダそのもの(DB に写さない):
  INBOX(未着手)→ 処理済み / 未処理 / 差戻し の各フォルダへ移動。
  状態=所在フォルダ。事務局アプリは「未処理」を IMAP で一覧し、
  代行入力(source='staff')や差し戻しの操作でメールを移動する。
  経路1(callback)の読取失敗は編集画面へのエラー表示が主で、保存済み
  xlsx を添えて未処理フォルダへ投函し同じ列に合流させる。
  障害時は普通のメールソフトでフォルダを開けば全件見える(引き継ぎ容易)。
  FAX・紙はメールが無いので、キューを経由せず代行入力画面から直接登録
```

- parse.py は「xlsx → 申込データ(Pydantic)」の純関数に保つ(I/O なし)。
  経路3の本文読取も同じ申込データ型に正規化して regist.py へ渡す
- 検証(必須・参加場所の提供有無・期限・会場定員)は parse/regist の境界で行い、
  エラー種別ごとに自動返信文面を分ける(02_api の 3.)

## 実装フェーズ

**Phase 0: 足場**
pyproject(ruff/pytest)・core(設定・DB)・models(schema.sql と1:1)・
no.py(採番)+テスト。
開発用 PostgreSQL は後日結線(下記テスト方針)。models は接続なしで書ける。

**Phase 1: 様式(心臓部)**
forms.py: 講座ごとの様式 xlsx 生成(名前付きセル・入力規則ドロップダウン・
シート保護・様式バージョン&講座IDセル・記入例シート・FAX印刷レイアウト)。
parse.py: 名前付きセル読取・版判定・検証。
テスト: 生成→記入(openpyxl でセルに値を入れる)→読取のラウンドトリップ、
不備パターン網羅(必須欠落・期限切れ・定員超過・提供外の参加場所・旧版様式)。

**Phase 2: 登録と静的サイト**
regist.py(upsert・採番・received_file)、sitegen.py+site/
(分類別一覧・講座ページ・アーカイブ・QR・様式配布)。
ローカルでビルド→成果物を目視確認。Pages への反映は cf-publish を利用(→確認事項3)。

**Phase 3: メール(経路2・3)**
mail.py(送信抽象。開発はメモリ/ファイルへのフェイク、本番SMTPリレー)、
mailin.py(IMAP ポーリング・(a)添付/(b)登録済み送信者の判別・自動返信・
フォルダ移動〔処理済み/未処理〕)。経路3の本文読取は「講座特定+受講者名+参加場所」の
緩い抽出とし、確信が持てない場合はキューへ。
テストは IMAP をフェイク(メッセージを直接注入)して結合まで。

**Phase 4: 事務局アプリと帳票**
office/(Flet): ダッシュボード/講座管理(保存で sitegen)/申込一覧/
未処理受信(IMAP「未処理」フォルダの一覧・代行入力 source='staff'・
差し戻し=フォルダ移動)/企業一覧/一斉送信/名簿・実績/
エクスポート/スタッフ(admin)。roster.py・ledger.py(openpyxl 直接生成)。
PocketBase ログインは認証部を抽象化し、開発はスタブ(→確認事項4)。

**Phase 5: 経路1と導入一式**
routers/docs(セッション発行・callback、JWT)+site/ の編集ページ、
deploy/(systemd・Caddy・バックアップ手順・操作手順書の骨子)。
OnlyOffice Document Server 実機での検証は導入フェーズ。

各フェーズ完了ごとにコミット(機能単位・日本語メッセージ)。

## テスト方針

- pytest。parse/forms/no/ledger/roster は純粋なロジックとして厚めに
- DB を使う結合テストは PostgreSQL 前提(TIMESTAMPTZ・gen_random_uuid)。
  **開発用 PostgreSQL の用意は後日**のため、DB 結合テストはマーカー
  (`@pytest.mark.db`)で分離し、DB が無い環境では自動スキップ。
  それまではロジック層のテストで進める
- メール・IMAP・PocketBase・OnlyOffice は抽象境界でフェイク差し替え

## 決定事項(2026-07-07 確認済み)

1. **未処理キュー = IMAP フォルダ**(DB テーブルは追加しない)。
   メールボックス自体をキューとして使い、状態は所在フォルダで表す
   (INBOX→処理済み/未処理/差戻し)。schema.sql は変更なし。
   原文はメールサーバーに原文のまま残り、メールソフトでも確認できる。
   処理の操作者記録は applications 側(source='staff'+事務局メモ)で足りる
2. **開発用 PostgreSQL**: 後日。それまで DB 結合テストはスキップ運用(上記)
3. **申込番号**: 採番方式を設定(SEMINAR_NO_STYLE)で切替可能にする
   (2026-07-08 更新。サンプル・教材としての価値も兼ねる——規模に道具を合わせる実例)。
   `seq`=全体通し連番(既定。例 2026-00042)/ `fy`=年度リセット /
   `fy-cat`=年度-分類-何回目(例 2026-DX-3。番号だけで内容がわかる小規模向け)。
   実装は no.py に閉じる
4. **PocketBase・OnlyOffice**: 開発中はスタブ、Phase 5 でまとめて実物結線
5. **様式・宛先の非公開**(2026-07-08): 公開サイトから form.xlsx と
   申込アドレスを撤去。様式と宛先は受領メール・印刷物・電話で個別に渡す
   (ボット収集・バックスキャッター対策)。添付なし・未登録送信者への
   自動返信(no_form)は廃止し、未処理フォルダ行きのみに。
   公開サイトの連絡先は電話等の公開用文言(SEMINAR_CONTACT_NOTE)
6. **様式の発行キー**(2026-07-08): 申込者にパスワードを持たせない代わりに、
   様式へ HMAC(SEMINAR_FORM_SECRET, 講座ID+様式版)の発行キーを
   非表示セルで埋め込み、パーサで検証(保存不要・ステートレス)。
   検証不可=発行物でない様式は Invalid → 未処理キューへ。
   secret 未設定時は検証オフ(開発用)。運用では必須の環境変数とする
