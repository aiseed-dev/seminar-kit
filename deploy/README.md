# deploy — 導入と運用(骨子)

対象: 機関内のローカルサーバー(1機関1式)。詳細は docs/04。
運用は機関の IT 人材へ移管する前提——この文書は引き継ぎ研修の教材を兼ねる。

## 構成

| ポート | もの | 公開 |
|---|---|---|
| 8000 | FastAPI(公開API) | Caddy 経由(Cloudflare のみ許可) |
| 8080 | OnlyOffice Document Server(コンテナ・JWT必須) | Caddy 経由 /onlyoffice |
| 8090 | PocketBase(スタッフ認証) | Caddy 経由 /auth |
| 8550 | 事務局アプリ(Flet Web) | **非公開**(LAN / SSH トンネル) |
| — | mailin(IMAP ポーリング常駐) | — |
| 5432 | PostgreSQL | ローカルのみ |

## 初期設定

1. 本リポジトリ(seminar-kit)を `/srv/seminar` に配置し、venv を作成:
   `git clone <リポジトリURL>/seminar-kit /srv/seminar`
   `cd /srv/seminar && python3 -m venv .venv && .venv/bin/pip install -e .`
2. `db/schema.sql` を PostgreSQL に適用
3. `/srv/seminar/.env` に設定を記入(SEMINAR_ プレフィックス):
   `SEMINAR_DB_URL` / `SEMINAR_SITE_BASE_URL` / `SEMINAR_SUBMIT_ADDR` /
   `SEMINAR_SMTP_*` / `SEMINAR_IMAP_*` / `SEMINAR_API_BASE_URL` /
   `SEMINAR_ONLYOFFICE_URL` / `SEMINAR_ONLYOFFICE_JWT_SECRET`(必須) /
   `SEMINAR_JITSI_BASE`
4. `deploy/systemd/*.service` を `/etc/systemd/system/` に置き、
   `systemctl enable --now seminar-api seminar-mailin seminar-office`
5. Caddy: `deploy/Caddyfile` を実ドメインに直して配置。
   443 の許可元を Cloudflare IP レンジに限定(ファイアウォール)
6. バックアップ: `deploy/backup.sh` を cron(毎晩)に登録し、
   **リストア演習を導入時に一度行う**(引き継ぎ研修の項目)
7. 様式マクロ(送信用テキスト生成): `deploy/form-macro.js` を
   OnlyOffice で様式に組み込み、動作を確認する(実機作業)。
   JS は自動生成(`python -m app.services.forms`)なので手で直さない。
   xlsx 生成時の自動埋め込みは実機で格納形式を確認してから実装する

## 日常運用

- デプロイ: `git pull` → `systemctl restart seminar-api seminar-mailin seminar-office`
  (短時間停止は許容。申込期限直前の時間帯を避ける)
- 静的サイトの反映: 事務局アプリの講座保存で自動再生成 → `dist/` を
  cf-publish 等で Cloudflare Pages へ
- 監視: Cloudflare Health Check(5分間隔・メール通知)
- メールが届かない/読み取れない場合: 事務局アプリ「未処理受信」を確認。
  アプリ機停止中もメールは受信箱に溜まり、復帰後に mailin が順に処理する
