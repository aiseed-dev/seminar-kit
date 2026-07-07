-- =====================================================================
-- 研修・セミナー管理システム スキーマ(seminar)
-- PostgreSQL 15+ / 1機関1式(シングルテナント)
--
-- 原則:
--  - 申込は xlsx 様式(神Excel を機械可読に設計したもの)のメール送付。
--    Web 入力フォームは持たない。読み取りは openpyxl
--  - 事務局スタッフのみ PocketBase(操作者の記録のため)
--  - 申込番号は DB 全体の通し番号(年+連番)。挿入時にアプリが採番して渡す
--  - 決済を持たない(受講料は fee_note の表示のみ)
-- =====================================================================

CREATE SCHEMA IF NOT EXISTS seminar;

-- 事務局スタッフ(PocketBase の身元に対応。申込者は登録しない)
CREATE TABLE seminar.staff (
    id            TEXT PRIMARY KEY,          -- PocketBase record id
    display_name  TEXT NOT NULL,
    contact_label TEXT,                      -- 担当部署名(例: 成長戦略推進部)
    role          TEXT NOT NULL DEFAULT 'staff'
                  CHECK (role IN ('staff', 'admin')),
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- 分類(支援メニューに対応: 人材育成 / 資金 / 経営相談 / 販路開拓 /
--       創業 / 改善活動 / 技術開発 / デジタル化・DX)
CREATE TABLE seminar.categories (
    id         SERIAL PRIMARY KEY,
    slug       TEXT NOT NULL UNIQUE,
    name       TEXT NOT NULL,
    sort_order INT NOT NULL DEFAULT 0
);

-- 講座(セミナー・研修)。公開分は静的サイトに生成される
CREATE TABLE seminar.courses (
    id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    title          TEXT NOT NULL,
    category_id    INT NOT NULL REFERENCES seminar.categories(id),
    summary        TEXT,                     -- 一覧用の一言
    description    TEXT,                     -- 概要(講師紹介・内容)
    starts_at      TIMESTAMPTZ NOT NULL,     -- 開催日時
    ends_at        TIMESTAMPTZ,
    venue_note     TEXT,                     -- 会場(名称・住所・案内)
    -- 参加場所の提供有無(現行の 会場 / ZOOM / サテライト会場 に対応)
    allow_venue     BOOLEAN NOT NULL DEFAULT true,
    allow_online    BOOLEAN NOT NULL DEFAULT false,
    allow_satellite BOOLEAN NOT NULL DEFAULT false,
    satellite_note  TEXT,                    -- サテライト会場名(例: toku-Noix)
    capacity_venue  INT,                     -- 会場定員(NULL=定員なし)。
                                             -- オンラインは定員管理しない
    fee_note       TEXT NOT NULL DEFAULT '無料',
    apply_deadline TIMESTAMPTZ NOT NULL,     -- 申込期限
    flyer_path     TEXT,                     -- チラシPDF
    online_note    TEXT,                     -- 受講方法・視聴環境・利用条件の定型文
    meeting_url    TEXT,                     -- オンライン配信URL。自営 Jitsi の
                                             -- ルームURLを講座作成時に自動生成
                                             -- (移行期は Zoom の URL も入れられる)。
                                             -- 公開せず、一斉送信でのみ受講者へ届ける
    status         TEXT NOT NULL DEFAULT 'draft'
                   CHECK (status IN ('draft', 'open', 'closed', 'finished')),
                   -- open=募集中 / closed=締切 / finished=開催済み
    attendance_count INT,                    -- 出席者数(開催後に事務局が入力。
                                             -- 年度実績台帳に反映)
    created_by     TEXT REFERENCES seminar.staff(id),
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_courses_open ON seminar.courses (starts_at)
    WHERE status = 'open';

-- 企業マスタ(事前登録)。初回申込(経路を問わず)で自動登録され、
-- 以後は担当者メールアドレスで引き当てる。二回目からの申込は
-- 「講座+受講者名+参加場所」だけの簡易メールで済む
CREATE TABLE seminar.companies (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    company_name  TEXT NOT NULL,
    company_kana  TEXT NOT NULL,
    contact_name  TEXT NOT NULL,
    contact_kana  TEXT NOT NULL,
    contact_email TEXT NOT NULL UNIQUE,      -- 引き当てキー(送信者アドレス)
    postal_code   TEXT NOT NULL,
    address       TEXT NOT NULL,
    tel           TEXT NOT NULL,
    fax           TEXT,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- 申込(企業単位。現行フォームの項目構成をそのまま写す。
--  企業情報は申込時点のスナップショットとして保持し、companies と紐付け)
CREATE TABLE seminar.applications (
    id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    course_id      UUID NOT NULL REFERENCES seminar.courses(id),
    company_id     UUID REFERENCES seminar.companies(id),
                                             -- 事前登録との紐付け(初回申込で
                                             -- 自動 upsert して以後引き当て)
    -- 申込番号: DB全体の通し番号(年+連番。例 2026-00042)。
    -- 挿入時にアプリが採番して渡す(既定値なし。UNIQUE衝突を防ぐ)
    application_no TEXT UNIQUE NOT NULL,
    app_year       INT,
    app_seq        INT,
    company_name   TEXT NOT NULL,
    company_kana   TEXT NOT NULL,
    contact_name   TEXT NOT NULL,            -- 担当者
    contact_kana   TEXT NOT NULL,
    contact_email  TEXT NOT NULL,
    postal_code    TEXT NOT NULL,
    address        TEXT NOT NULL,
    tel            TEXT NOT NULL,
    fax            TEXT,
    status         TEXT NOT NULL DEFAULT 'confirmed'
                   CHECK (status IN ('confirmed',  -- 受付済み
                                     'cancelled')),
                   -- 申込は xlsx 様式のメール送付で受け付ける。本人のメール
                   -- アドレスから届くため確認トークンは不要(受領メールの
                   -- 返信で足りる)。キャンセルはメール依頼→事務局が処理
    source         TEXT NOT NULL DEFAULT 'mail'
                   CHECK (source IN ('mail',   -- 様式xlsxメールの自動読み取り
                                     'quick',  -- 事前登録済みの簡易メール
                                     'web',    -- ブラウザ記入(OnlyOffice Docs)
                                     'staff')),-- FAX・紙を事務局が代行入力
    received_file  TEXT,                      -- 受信した申込xlsxの保存パス
                                             -- (原本の監査証跡)
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    note           TEXT                      -- 事務局メモ
);

CREATE INDEX idx_apps_course ON seminar.applications (course_id, created_at);

-- 受講者(1申込につき1〜3名。現行フォームと同じ上限を既定とするが
--         テーブル構造上は可変)
CREATE TABLE seminar.attendees (
    id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    application_id UUID NOT NULL REFERENCES seminar.applications(id)
                   ON DELETE CASCADE,
    name           TEXT NOT NULL,
    kana           TEXT NOT NULL,
    title_role     TEXT NOT NULL,            -- 所属・役職
    email          TEXT NOT NULL,            -- Zoom接続情報の送付先
    location       TEXT NOT NULL
                   CHECK (location IN ('venue', 'online', 'satellite')),
    -- 個人別の出欠は DB で持たない(当日名簿は xlsx で出力し、
    -- 受付は紙でチェックする運用)。実績は下記 attendance_count のみ
    sort_order     INT NOT NULL DEFAULT 1
);

CREATE INDEX idx_attendees_app ON seminar.attendees (application_id);

-- 一斉送信の記録(Zoom接続情報・リマインド・開催案内の変更等)
CREATE TABLE seminar.mails (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    course_id       UUID NOT NULL REFERENCES seminar.courses(id),
    subject         TEXT NOT NULL,
    body            TEXT NOT NULL,
    target          TEXT NOT NULL DEFAULT 'all'
                    CHECK (target IN ('all', 'venue', 'online', 'satellite')),
                    -- 宛先の絞り込み(confirmed の受講者のみが対象)
    recipient_count INT NOT NULL,
    sent_by         TEXT REFERENCES seminar.staff(id),
    sent_at         TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- アンケートのテーブルは意図的に存在しない。
-- アンケートは紙で実施し、回収後にローカルLLM(Command A+ 等)で
-- 読み取り・集計・要約する(docs/05 参照)。システムは関与しない。

-- updated_at トリガ
CREATE OR REPLACE FUNCTION seminar.touch_updated_at()
RETURNS trigger AS $$
BEGIN NEW.updated_at = now(); RETURN NEW; END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_courses_touch BEFORE UPDATE ON seminar.courses
    FOR EACH ROW EXECUTE FUNCTION seminar.touch_updated_at();
CREATE TRIGGER trg_companies_touch BEFORE UPDATE ON seminar.companies
    FOR EACH ROW EXECUTE FUNCTION seminar.touch_updated_at();
