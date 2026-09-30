# API エンドポイント仕様 — フロントエンド連携ガイド

[English](api-spec.md) | 日本語

`../CLAUDE.md`、`architecture_JP.md`、`database-design_JP.md`、`project_status_JP.md`（同じ `docs/` フォルダ）と対になる
ドキュメントです。それらはシステムを説明するもので、このファイルは引き継ぎのための窓口です — バックエンドが現在
公開しているすべてのルートを、フロントエンドがそれを使うページごとにまとめているので、ページの一覧に沿って UI を
作り、その後セクションごとに実際のエンドポイントにつなぎ込めます。

`app/router/` と `app/schema/` の実際のルート／スキーマ定義から生成したもの（手で書き写したものではない）なので、
以下のメソッド／パス／パラメータ名はコードと正確に一致します。`response_model` を宣言しているエンドポイントの
レスポンスの *形* は Pydantic で強制されており信頼できます。`response_model` を持たず素の dict や ORM オブジェクトを
返すエンドポイントもいくつかあり（エンドポイントごとに記載）— その形はサービス／ルーターの実際の `return` 文から
記述していますが、FastAPI が強制しているわけではないので、契約ではなく「現時点での最善の記述」として扱ってください。
「フロントエンドでは未使用」と記したルートは、ルーターのソースにも同じコメントがあります。

## 0. 規約

**ベース URL。** グローバルなプレフィックスはない — 以下のすべてのパスはアプリのルートにマウントされている
（`main.py` は `prefix=` なしで `app.include_router(...)` を行う）。対話的なドキュメントは `/docs`（同じルート定義から
自動生成される Swagger UI）と `/redoc` で提供される — サーバーが動いていれば正確なスキーマを実際に確認するのに便利で、
このファイルはサーバーがない状態や動かす前に UI を計画するためのもの。

**認証。** JWT の Bearer トークン。`POST /account/login`（§1 を参照）で取得し、以下で 🔒 の付いたすべてのエンドポイント
で `Authorization: Bearer <access_token>` として送る — アクセストークンの保存と付与はフロントエンドの責任である。
**リフレッシュトークン** は違う: ログインと `/account/refresh` はそれを `refresh_token` という名前の
`httponly; secure; samesite=none` の Cookie として設定するので、フロントエンドがそれを見ることはなく、ローテーション
するには認証情報を含めて（`fetch(..., {credentials: "include"})` / `withCredentials`）`/account/refresh` を呼ばなければ
ならない。🔒 のエンドポイントへのリクエストで、トークンがない／不正／期限切れなら `401`、トークンは有効だがロールが
違えば `403`（ロールの凡例を参照）。`require_manager_or_admin` は *ロール* だけをチェックし、事務所の所有関係は
チェックしない — いくつかのサービスは、マネージャーが自分の事務所のリソースの外で操作した場合にさらに 403 を返す
（エンドポイントごとに「事務所スコープあり」と記載）。

**ロールの凡例**（`app/deps/auth.py` より、`Users.role` に対してチェック）:
- 🔓 — 認証不要（公開）
- 🔒 fan — 認証済みの任意のユーザー（`get_current_user`）。ログインしていること以外のロールの制限なし
- 🔒 manager+ — `require_manager_or_admin`: ロールが `manager` または `admin`
- 🔒 admin — `require_admin`: ロールが `admin` のみ

**エラーの形。** すべてのエラーボディは `{"detail": ..., "code": "<snake_case>"}`。
- `detail` は人間が読める英語の文字列 — ただしリクエスト検証による `422` の場合は、FastAPI の `{loc, msg, type}` の
  フィールドエラーのリストになる。せいぜい補足のテキストとして表示し、解析はしないこと。
- `code` は安定している: UI ではこれで分岐（し、翻訳）する。一覧にないコードが後で追加されることもある —
  その場合はステータスコードにフォールバックすること。

| コード | ステータス | 発生する場面 |
|---|---|---|
| `not_authenticated` | 401 | アクセストークンがない、不正、期限切れ、またはそのユーザーがもう存在しない |
| `invalid_credentials` | 401 | `POST /account/login`: メールアドレスまたはパスワードが違う |
| `invalid_refresh_token` | 401 | `POST /account/refresh`: Cookie がない、期限切れ、または失効済み |
| `invalid_token` | 400 / 401 | メール認証のリンク（400）またはパスワードリセットのトークン（401）が不正または期限切れ |
| `incorrect_password` | 400 | `PUT /profile/change-password`: 現在のパスワードが違う |
| `email_taken` | 400 | 既存のメールアドレスでの登録／マネージャーの作成 |
| `already_verified` | 409 | 認証済みのアカウントでの `GET /account/verify` |
| `forbidden` | 403 | ロールが違う、またはマネージャーが自分の事務所の外で操作した |
| `fan_only_purchase` | 403 | マネージャーまたは管理者が購入、カートへの追加、抽選への参加を試みた |
| `not_found` | 404 | 要求されたリソースが存在しない（または呼び出し元のものではない） |
| `validation_error` | 422 | リクエストのボディ／クエリ／パスの検証に失敗した |
| `rate_limited` | 429 | リクエストが多すぎる。`detail` に何秒待てばよいかが書かれている |
| `method_not_allowed` | 405 | HTTP メソッドが違う |
| `internal_error` | 500 | 予期しないサーバーエラー（サーバー側でログに出力）。読み取りは再試行しても安全 |
| `invalid_image` | 400 | 画像のアップロードが拒否された: 未対応の形式、5 MB 超過、またはストレージの設定ミス |
| `insufficient_stock` | 400 | カートへの追加または注文の購入手続き: 在庫が足りない |
| `cart_empty` | 404 | 空のカートでの `POST /order/checkout` |
| `address_not_found` | 404 | 存在しない配送先住所での購入手続き |
| `amount_mismatch` | 400 | 購入手続きの `amount` が現在の合計と一致しない（価格が変わった — 再取得すること） |
| `unsupported_gateway` | 400 | 未知の `gateway` の値 |
| `resale_cap_exceeded` | 400 | ファンごとに 1 つの商品を 3 個より多く |
| `duplicate_idempotency_key` | 409 | 使用済みの `idempotency_key` で購入手続きを再試行した（二重送信） |
| `ticket_type_not_found` | 404 | 存在しない券種での `POST /tickets/checkout` |
| `wrong_sale_method` | 400 | 抽選のティアを直接購入した、または一般販売のティアに順位を付けた |
| `not_on_sale` | 400 | 現在の時刻をカバーする open な一般販売キャンペーンがない |
| `sold_out` | 400 | そのティアに残りの席がない |
| `duplicate_concert_ticket` | 400 | ファンがこの公演の有効なチケットをすでに持っている |
| `lottery_entry_unresolved` | 400 | その公演の pending または当選した抽選の応募があるため、一般販売での購入がブロックされた |
| `ticket_not_found` | 404 | 存在しない、または呼び出し元のものではない当選チケットの支払い |
| `ticket_not_payable` | 400 | そのチケットは未払いの抽選当選チケットではない |
| `payment_deadline_passed` | 400 | 抽選当選の支払い期限が過ぎた。チケットは失効済み |
| `ranking_locked` | 400 | 受付終了後に抽選の順位を変更しようとした |
| `no_lottery_campaign` | 404 | 抽選キャンペーンのないティアに順位を付けた |
| `entries_not_open` | 400 | 受付期間の開始前に順位付けまたは応募をした |
| `entries_closed` | 400 | 受付期間の終了後に応募した |
| `campaign_not_open` | 400 | すでに抽選済みのキャンペーンに応募した |
| `campaign_cancelled` | 400 | キャンセルされたキャンペーンに応募した |
| `tier_already_applied` | 400 | ファンがすでに応募した、順位付けしたティアを削除しようとした |
| `duplicate_ranked_tier` | 400 | 1 つの順位付けに同じティアが 2 回 |
| `lottery_preference_required` | 400 | ファンが順位を付けていないティアに応募した |
| `lottery_entry_cap_exceeded` | 400 | このキャンペーンにはすでに応募済み |
| `no_open_campaigns` / `entries_not_ended` | 400 | 抽選の実行が早すぎる、または抽選するものがない（マネージャー） |
| `order_already_shipped` / `order_cancelled` / `invalid_shipping_transition` | 400 | 現在のステータスからは注文のキャンセル／発送ステータスの変更が許されない（マネージャー／管理者） |
| `bad_request` / `conflict` / `rule_violation` | 400 / 409 / 400 | 汎用的なフォールバック。主にマネージャー／管理者のフォームのチェック — `detail` を表示する |
| その他のトリガーのコード | 400 | `ticket_type_concert_mismatch`、`product_detail_kind_conflict`、`concert_capacity_exceeded`、`duplicate_ticket_type`（マネージャー／管理者のフォーム） |

**空の結果は決してエラーではない。** すべてのリストのエンドポイントは、一覧にするものがなければ `200 []` を返し、
ページのエンドポイント（`/products/store-page`、`/concerts/events-page`、`/idols/members-page`、`/groups/groups-page`）は
空のリストを持つオブジェクトを返す。空のカートでの `GET /cart/see_cart` は `{"items": [], "total_price": 0}` を返す。
`404` は常に、特定のリソースが存在しないことを意味する。

エラーではない決済の結果: 拒否されたモック決済は、注文またはチケットの `status: "cancelled"` とともに **200** を返す。
PayPal の購入手続きは `status: "pending"` とともに **200** を返す。

いくつかのエンドポイントは、単純な操作（削除、パスワードの変更）の成功時に、リソースそのものではなく
`{"msg": "<message>"}` を返す — フロントエンドがレスポンスから楽観的に更新できるか、再取得しなければならないかに
影響するので、以下でエンドポイントごとに明記している。

**ページネーション。** いくつかのエンドポイントは `page`/`limit` のクエリパラメータを取り、
`{"page", "limit", "count", "data"}` を返す: `GET /products/pagination`、`GET /products/filter`、そしてマネージャー側の
`GET /order/manager-orders-page`、`GET /products/{id}/sales`、`GET /tickets/concert/{id}/sales`。`count` は合計ではなく
返されたページのサイズ（`docs/bugs_JP.md` #23）なので、まだ「最後のページ」を示す信頼できる合図はない — ページが
短く返ってきたら止めること。それ以外のすべてのリストのエンドポイントは、ページネーションなしでコレクション全体を
返す。

**ページのエンドポイント。** 多くの画面には、そのページに必要なものをすべて 1 回のレスポンスで返す `*-page` または
`/{id}/detail` のエンドポイントが 1 つある（例: `GET /products/store-page`、`GET /concerts/{id}/detail`）。これらは
Redis でキャッシュされている（TTL 5 分、書き込み時に無効化）ので、以下のリソースごとの CRUD の読み取りをつなぎ
合わせるよりも、これらを優先すること。`manager-*-page` の読み取りは 🔒 manager+ で、**サーバー側で事務所に
スコープされている**: マネージャーは常に自分の事務所の行（と所有者のない商品）だけを受け取り、`company_id` を渡して
事務所を選べるのは管理者だけである。フロントエンドがそれらを事務所でフィルタする必要はない。

**画像のアップロード。** `POST /idols/add` と `POST /products/add_product` は JSON ではなく `multipart/form-data` で
ある — この一覧の他のすべての書き込み系エンドポイントは JSON。正確なフォームのフィールドは §3（`Idols`）と §5
（`Products`）を参照。アップロードされた画像は、バックエンドのデプロイ設定に応じて、`LOCAL_UPLOAD_URL_PREFIX` が
解決する先（デフォルト `/uploads/...`）か、本物の S3／CDN の URL から配信される — どちらにしても、レスポンスの
`image_url`/`profile_image_url` はそのまま使える `<img src>` である。

**レート制限。** ほとんどのエンドポイントは、ティアポリシー（`architecture_JP.md` §3）によって IP ごとまたはユーザー
ごとにレート制限されている: 認証とお金／在庫の書き込みは厳しく（3〜10/分）、ポーリングされる読み取りはゆるい
（最大 60/分）。`429` は間隔をあけろという意味で、バグではない。その `detail` に何秒待てばよいかが書かれている。
以下では網羅的には挙げていない — 再試行／バックオフの戦略に特定の上限が関係する場合は、各ルートの
`rate_limit(...)` の依存性を参照すること。

## 1. フロントエンドのページ構成の提案

利用者ごとにまとめた、出発点としてのページの一覧と、それぞれが使うエンドポイントのセクション。規定ではない —
バックエンドが現在実際にサポートしているものにきれいに対応する形にすぎず、すべてのエンドポイントがつなぎ込まれる
前に UI の骨組みを作れるようにするためのもの。

**公開（ログイン不要）:**
- ホーム／ランディング — アイドル、グループ、今後の公演のハイライト（§3、§4）
- メンバーページ／アイドルのプロフィール — `GET /idols/members-page`、`GET /idols/{id}/detail`（§3）
- グループページ／グループのプロフィール — `GET /groups/groups-page`、`GET /groups/{id}/detail`（§3）
- イベントページ／公演の詳細 — `GET /concerts/events-page`、`GET /concerts/{id}/detail`（§4。詳細ページは、サインイン
  しているファン自身のチケット／抽選の状態も持つ）
- ストア + 商品の詳細 — `GET /products/store-page`、`GET /products/{id}/detail`（§5）
- お問い合わせページ — §8 `Inquiries`（FAQ の即時回答、その後フォーム）
- ログイン／登録／メール認証／パスワード忘れ／パスワードリセット — §2

**ファン（ログイン済み、任意のロール）:**
- マイプロフィール — §2 `Profile`
- カート — §6 `Cart`
- 購入手続き — §6 `Order`（`/checkout`）、`Shipping Addresses`、`Payment`
- 注文履歴（一覧 + 詳細 + キャンセル + 発送ステータス）— §6 `Order`
- 支払い状況 — §6 `Payment`
- マイチケット — §4 `Tickets`（`/mine`）
- 抽選: キャンペーンへの応募、券種の希望の順位付け、自分の応募の確認、当選チケットの支払い — §4
  `Lottery Campaigns`、`Lottery Preferences`、`Lottery Entries`、`Tickets`
- 一般販売チケットの購入 — §4 `Tickets`（`/checkout`）、一般販売キャンペーンが open な間
- 通知 — §7

**マネージャー（自分の事務所のアイドル／グループ／公演／商品）:**
- マネージャーのダッシュボード — 以下のセクションへの入り口で、自分の `company_id` にスコープされる
- アイドル／グループ／ポジション／メンバーカラーの管理 — §3（作成／編集。カラーの削除は管理者専用）
- 公演、券種、出演者の割り当て、抽選と一般販売のキャンペーンの管理 — §4。公演の抽選の実行
  （`PUT /concerts/lottery-draw/{id}`）と結果の確認
- 発送待ちの注文 — `GET /order/manager-orders-page`、`PATCH /order/{order_id}/ship`（§6）
- 商品、アルバムの詳細、グッズの詳細、ジャンルの割り当ての管理 — §5（商品画像のアップロード／置き換え、更新、削除は
  事務所スコープあり — `Products` の下の 403 に関する注記を参照）

**管理者（サイト全体）:**
- 事務所の管理 — §2 `Management Companies`
- カテゴリ、ジャンル（削除）、会場の管理 — §5、§4
- ユーザーの管理者への昇格 — §2 `Profile`（`/make-admin`）
- チケットの手動発行／編集／削除 — §4 `Tickets`（サポート／テスト用のツール。通常のチケットは抽選または一般販売の
  購入から生まれる）
- 注文の発送ステータスの更新 — §6 `Order`（`/update_shipping_status`）
- 任意のメンバーカラー／ジャンル／ポジション／会場／事務所の削除 — manager+ が作成／更新できるものでも、削除は
  一律に管理者専用（各セクションのロールの列を参照）

---

## 2. アカウントとプロフィール

### `POST /account/register` 🔓
新しいユーザーアカウントを作成する（ロールのデフォルトは `fan` — 呼び出し元が自分で `manager`/`admin` を割り当てる
手段はここにはない）。
- リクエスト（JSON — `UserCreate`）: `name`（str）、`email`（str、検証済みのメールアドレス）、`password`（str、
  6〜128 文字）
- レスポンス（`UserOut`）: `id`、`name`、`email`、`role`（`"admin"|"manager"|"fan"` — ここでは常に `"fan"`）、
  `company_id`（uuid、nullable — ここでは常に `null`）、`is_active`、`is_admin`、`is_verified`、`created_at`、
  `updated_at`
- UI: 登録ページ

### `POST /account/login` 🔓
OAuth2 のパスワードグラント — すべての 🔒 エンドポイントのためのトークンの入手元。
- リクエスト: `application/x-www-form-urlencoded`（JSON ではなく OAuth2 のフォーム）— `username`（このフィールドに
  ユーザーの **メールアドレス** を送る）、`password`
- レスポンス: スキーマで強制されていない。標準的なトークンのペア（`access_token`、`refresh_token`、`token_type`）
- UI: ログインページ。レート制限あり（10/分/IP）。

### `POST /account/refresh` 🔓
リフレッシュトークンを新しいアクセストークンと交換する。
- リクエスト: リクエストからリフレッシュトークンを読む（`Request` パラメータ、宣言されたボディのスキーマはない —
  つなぎ込む前に、現在の Cookie／ボディの規約を `/docs` で確認すること）
- レスポンス: スキーマで強制されていない。新しいトークンのペア
- UI: アクセストークンの期限切れ時のバックグラウンドでの呼び出しで、ユーザー向けの画面ではない

### `POST /account/verify-request` 🔒 fan
現在のユーザーにメール認証のリンクを送る／再送する。
- リクエスト: なし
- レスポンス: スキーマで強制されていない
- UI: 「認証メールを再送」ボタン（例:「メールアドレスを認証してください」のバナー上）

### `GET /account/verify` 🔓
認証リンクのトークンでメールアドレスを確認する。
- リクエスト: クエリパラメータ `token`（str）
- レスポンス: `{"msg": "Email verified successfully"}`
- エラー: `400`（不正または期限切れのトークン、またはトークンのユーザーがもう存在しない）、`409`（アカウントは
  すでに認証済み）
- UI: 認証メールのリンクが開くランディングページ

### `GET /profile/me` 🔒 fan
- レスポンス（`UserOut`）: 登録のレスポンスと同じ形 — `role`/`company_id` が含まれるので、フロントエンドは
  `currentUser.role`/`currentUser.company_id` を直接読める
- UI: プロフィールページ、ヘッダーのユーザーメニュー

### `PUT /profile/change-password` 🔒 fan
- リクエスト（`ChangePasswordRequest`）: `old_password`（str）、`new_password`（str、6〜128 文字）
- レスポンス: `{"msg": "Password changed succesfully"}`
- UI: アカウント設定

### `POST /profile/forgot-password` 🔓
- リクエスト（`ForgotPasswordRequest`）: `email`
- レスポンス: `{"msg": "reset link sent successfully"}`
- UI:「パスワードをお忘れですか？」のフロー、ステップ 1

### `POST /profile/set-password` 🔓
メールで送られたリンクのトークンを使ってパスワードリセットを完了する。
- リクエスト（`SetPasswordRequest`）: `token`（str）、`new_password`（str、6〜128 文字）
- レスポンス: `{"msg": "password changed successfully"}`
- UI:「パスワードをお忘れですか？」のフロー、ステップ 2（リンクの遷移先）

### `POST /profile/make-admin` 🔒 admin
- リクエスト（`MakeAdminRequest`）: `user_id`（uuid）
- レスポンス: `{"msg": "user <id> promoted to admin successfully"}`
- UI: 管理者のユーザー管理画面

### `POST /profile/create-manager` 🔒 admin
事務所に紐づく新しい `role="manager"` のアカウントを 1 回の呼び出しで作成する — `/make-admin` は *既存のユーザーを
昇格させる* だけで事務所の概念を持たないので、それとは別物である。「事務所のユーザーアカウントを作成する」フローに
はこれを使う。
- リクエスト（`ManagerCreate`）: `name`（str）、`email`（str、検証済みのメールアドレス）、`password`（str、6〜128 文字）、
  `company_id`（uuid、既存の事務所を参照しなければならない）
- レスポンス（`UserOut`）: 登録のレスポンスと同じ形 — `role` は `"manager"`、`company_id` は指定した事務所
- エラー: `400`（メールアドレスは登録済み）、`404`（company_id が存在しない）
- UI: 管理者の「事務所のユーザーを作成」画面

### `POST /profile/logout` 🔓
現在のリフレッシュトークンを無効にする。
- リクエスト: なし（`Request` から読む）
- レスポンス: スキーマで強制されていない
- UI: ログアウトボタン

### `DELETE /profile/delete` 🔒 fan
呼び出し元自身のアカウントを削除する。
- レスポンス: `{"msg": "user <id> deleted successfully"}`
- UI: アカウント設定の「アカウントを削除」、確認の後

### `POST /management_companies/add` 🔒 admin
- リクエスト（`ManagementCompanyCreate`）: `name`（str）、`description`（str、任意）、`contact_email`（str、任意）
- レスポンス（`ManagementCompanyRead`）: `id` が加わる
- UI: 管理者 — 事務所の管理

### `GET /management_companies/all` 🔓
- レスポンス: `List[ManagementCompanyRead]`
- UI: 管理者の事務所一覧。マネージャーの登録やアイドル／グループのフォームで事務所の選択肢が必要な場所ならどこでも

### `GET /management_companies/{id}` 🔓
- レスポンス: `ManagementCompanyRead`
- UI: 事務所の詳細（管理者）

### `PUT /management_companies/update/{id}` 🔒 admin
- リクエスト（`ManagementCompanyBase`）: `name`、`description`、`contact_email`
- レスポンス: `ManagementCompanyRead`
- UI: 管理者 — 事務所の編集

### `DELETE /management_companies/delete/{id}` 🔒 admin
- レスポンス: `{"msg": "Management company deleted successfully"}`
- UI: 管理者 — 事務所一覧

---

## 3. タレント — アイドル、グループ、ポジション、カラー

### `POST /idol_colors/add` 🔒 manager+
アイドルの「ブランドカラー」（アイドルのプロフィール／ペンライトのテーマ付けに使う — `database-design_JP.md` を参照）。
- リクエスト（`IdolColorCreate`）: `name`（str）、`hex_code`（str、`^#[0-9A-Fa-f]{6}$`）
- レスポンス（`IdolColorRead`）: `id` が加わる
- UI: マネージャー — カラーの選択肢の管理（通常は独立したページではなく、小さな再利用可能なリスト）

### `GET /idol_colors/all` 🔓
- レスポンス: `List[IdolColorRead]`
- UI: アイドルを作成／編集するあらゆる場所でのカラーのドロップダウン

### `PUT /idol_colors/update/{id}` 🔒 manager+
- リクエスト（`IdolColorBase`）: `name`、`hex_code`
- UI: マネージャー — カラーの編集

### `DELETE /idol_colors/delete/{id}` 🔒 admin
- レスポンス: `{"msg": "Idol color deleted successfully"}`
- UI: カラーはそれ以外ではマネージャーが編集できるが、削除は管理者のみ

### `POST /positions/add` 🔒 manager+
ポジション／役割のカタログ（例:「Leader」、「Main Vocalist」）— 事務所ごとではなく、すべてのグループで共有される。
- リクエスト（`PositionCreate`）: `name`（str）
- レスポンス（`PositionRead`）: `id` が加わる
- UI: マネージャー — ポジションのカタログの管理

### `GET /positions/all` 🔓
- レスポンス: `List[PositionRead]`
- UI: メンバーをグループに割り当てるときのポジションの選択肢

### `PUT /positions/update/{id}` 🔒 manager+
- リクエスト（`PositionBase`）: `name`

### `DELETE /positions/delete/{id}` 🔒 admin
- レスポンス: `{"msg": "Position deleted successfully"}`

### `POST /positions/idol_positions/assign` 🔒 manager+
アイドルにポジションを割り当てる。
- リクエスト（`IdolPositionAssign`）: `idol_id`（uuid）、`position_id`（uuid）、`is_primary`（bool、デフォルト `false`）
- レスポンス（`IdolPositionRead`）: `idol_id`、`position_id`、`is_primary`、ネストした `position`（`PositionRead`）
- UI: アイドルの編集ページ —「役割」のセクション

### `GET /positions/idol_positions/idol/{idol_id}` 🔓
- レスポンス: `List[IdolPositionRead]`
- UI: アイドルのプロフィールページ — 役割のバッジ（例:「Main Vocalist」）

### `GET /positions/idol_positions/all` 🔓
フロントエンドでは未使用。
- レスポンス: `List[IdolPositionRead]`（`idol_id`、`position_id`、`is_primary`、`position`）
- エラー: まだポジションを持つアイドルがいなければ `404`

### `PUT /positions/idol_positions/{idol_id}/{position_id}` 🔒 manager+
このポジションがアイドルのメインのものかどうかを切り替える。
- リクエスト: クエリ／ボディのパラメータ `is_primary`（bool）— リクエストのスキーマはなく、素のパラメータ
- レスポンス（`IdolPositionRead`）
- UI: アイドルの編集ページ —「メインの役割に設定」

### `DELETE /positions/idol_positions/{idol_id}/{position_id}` 🔒 manager+
- レスポンス: `{"msg": "Position unassigned from idol successfully"}`
- UI: アイドルの編集ページ — 役割の削除

### `POST /groups/add` 🔒 manager+
- リクエスト（`GroupCreate`）: `name`（str）、`debut_date`（date、任意）、`description`（str、任意、2000 文字以内）、
  `company_id`（uuid）
- レスポンス（`GroupRead`）: `id`、`is_active`（作成時は常に `true`）、`created_at`、`updated_at` が加わる
- UI: マネージャー — グループの作成

### `GET /groups/all` 🔓
- レスポンス: `List[GroupRead]` — **`is_active=True` のグループのみ**（database-design_JP.md §3.3）
- UI: グループのディレクトリ／ホームページのカルーセル

### `GET /groups/{id}` 🔓
- レスポンス: `GroupRead` — 意図的に `is_active` で **フィルタしない** ので、マネージャーの編集フォームは無効化された
  グループも読み込める
- UI: グループのプロフィールページ、マネージャーの編集フォーム

### `GET /groups/groups-page` 🔓
公開のグループページに必要なものすべて、キャッシュあり。
- レスポンス（`GroupsPageRead`）: `groups` — それぞれ `GroupRead` に `member_count` が加わったもの
- エラー: グループがなければ `404`
- UI: 公開のグループ一覧

### `GET /groups/{id}/detail` 🔓
- レスポンス（`GroupDetailRead`）: `group`（`GroupRead`）、`members`（ポジション、カラー、グループ付きのアイドル）、
  `events`（会場付きの公演）、`products`（グループにクレジットされている `ProductCard`）
- エラー: グループが存在しなければ `404`
- UI: グループのプロフィールページ

### `GET /groups/manager-groups-page` 🔒 manager+ (company-scoped)
- レスポンス（`ManagerGroupsPageRead`）: `groups`（`List[GroupRead]`）— マネージャーには自分の事務所のグループ、
  管理者にはすべての事務所のもの。無効なグループも含まれる（`is_active`）
- エラー: トークンなしなら `401`、ファンなら `403`
- UI: マネージャー — グループのテーブル

### `PUT /groups/update/{id}` 🔒 manager+ (company-scoped)
- リクエスト（`GroupUpdate`）: `name`、`debut_date`、`description` — `is_active` はここでは **設定できない**。下の
  削除／有効化のエンドポイントを使う
- UI: マネージャー — グループの編集

### `DELETE /groups/delete/{id}` 🔒 manager+ (company-scoped)
論理削除 — `is_active = false` にし、行は削除しない（database-design_JP.md §3.3）。
- レスポンス: `{"msg": "Group deleted successfully"}`

### `PATCH /groups/activate/{id}` 🔒 manager+ (company-scoped)
上の削除を元に戻す — `is_active = true` にする。
- レスポンス（`GroupRead`）: 再有効化されたグループ全体
- UI: マネージャー — 設定ページ、無効化されたグループの「再有効化」

### `POST /idols/add` 🔒 manager+ — **multipart/form-data**, not JSON
（JSON ではなく **multipart/form-data**）
- リクエスト（フォームのフィールド）: `name`（str、必須）、`company_id`（uuid、必須）、`group_id`（uuid、任意）、
  `date_of_birth`（date、任意）、`hometown`（str、任意）、`color_id`（uuid、任意）、`short_intro`（str、任意、500 文字
  以内）、`long_description`（str、任意）、`image`（ファイル、任意 — 最大 5MB、`image/jpeg|png|webp|gif`）
- レスポンス（`IdolRead`）: 上記すべてに加えて `id`、`is_active`（作成時は常に `true`）、`profile_image_url`、
  `created_at`、`updated_at`
- `group_id` が無効化されたグループを指している場合は `400` — 無効なグループに新しいメンバーを割り当てることは
  できない（database-design_JP.md §3.3）
- UI: マネージャー — アイドルの作成（同じフォームで写真もアップロード）

### `GET /idols/all` 🔓
- レスポンス: `List[IdolRead]` — **`is_active=True` のアイドルのみ**（database-design_JP.md §3.4）
- UI: アイドルのディレクトリ／ホームページ

### `GET /idols/{id}` 🔓
- レスポンス: `IdolRead` — 意図的に `is_active` で **フィルタしない** ので、マネージャーの編集フォームは無効化された
  アイドルも読み込める
- UI: アイドルのプロフィールページ、マネージャーの編集フォーム

### `GET /idols/members-page` 🔓
- レスポンス（`MembersPageRead`）: `idols`（それぞれ `idol_positions`、`color`、`group` 付き）、`groups`（`id`、`name`
  — フィルタのコントロール用）
- エラー: アイドルがいなければ `404`
- UI: 公開のメンバーページ

### `GET /idols/{id}/detail` 🔓
- レスポンス（`IdolDetailRead`）: `idol`（ポジション、カラー、グループ付き）、`group`（`id`、`name`、`description`、
  ソロのアイドルなら `null`）、`siblings`（同じグループの他のメンバー）
- エラー: アイドルが存在しなければ `404`
- UI: アイドルのプロフィールページ

### `GET /idols/manager-idols-page` 🔒 manager+ (company-scoped)
- レスポンス（`ManagerIdolsPageRead`）: `idols`（`List[IdolRead]`、無効なものも含む）、`groups`（`id`、`name` —
  それらのアイドルが所属するグループで、テーブルの「グループ」列用）。マネージャーには自分の事務所のもの、管理者には
  すべての事務所のもの
- エラー: トークンなしなら `401`、ファンなら `403`
- UI: マネージャー — アイドルのテーブル

### `GET /idols/manager-idol-form-page` 🔒 manager+ (company-scoped)
- レスポンス（`ManagerIdolFormPageRead`）: `idols`、`groups`（`id`、`name`、`company_id`、`is_active` — グループの
  選択肢用）、`colors`（`List[IdolColorRead]`、すべての事務所で共有）。`idols`/`groups` はマネージャーの自分の事務所の
  もの。管理者はすべての事務所のものを受け取り、フォームで選んだ事務所でグループの選択肢をフィルタする
- エラー: トークンなしなら `401`、ファンなら `403`
- UI: マネージャー — アイドルの作成／編集フォーム

### `PUT /idols/update/{id}` 🔒 manager+ (company-scoped) — **JSON**, not multipart
（multipart ではなく **JSON**）
画像以外のすべてのフィールドを更新する — 画像には下の専用の画像エンドポイントを使う。
- リクエスト（`IdolUpdate`）: `IdolCreate` と同じフィールドから `company_id` を除いたもの（所有者は変更できない）—
  `is_active` はここでは **設定できない**。下の削除／有効化のエンドポイントを使う
- `group_id` が無効化されたグループを指していて、**かつそれが実際の変更である** 場合は `400` — アイドルの現在の
  （すでに無効化された）`group_id` をそのまま送り直すのは許され、アイドルを無効なグループに *移す* ことだけが拒否
  される（database-design_JP.md §3.3）
- UI: マネージャー — アイドルの編集（テキストのフィールド）

### `DELETE /idols/delete/{id}` 🔒 manager+ (company-scoped)
論理削除 — `is_active = false` にし、行は削除しない（database-design_JP.md §3.4）。
- レスポンス: `{"msg": "Idol deleted successfully"}`

### `PATCH /idols/activate/{id}` 🔒 manager+ (company-scoped)
上の削除を元に戻す — `is_active = true` にする。
- レスポンス（`IdolRead`）: 再有効化されたアイドル全体
- UI: マネージャー — 設定ページ、無効化されたアイドルの「再有効化」

### `POST /idols/{id}/image` 🔒 manager+ (company-scoped)
他のフィールドには触れずに、アイドルの写真だけを置き換える。
- リクエスト: `multipart/form-data`、`image`（ファイル、必須）
- レスポンス（`IdolRead`）: 更新されたアイドル全体
- UI: マネージャー — アイドルの編集、「写真を変更」のコントロール（メインの編集フォームの保存とは別）

---

## 4. イベントとチケット

### `POST /venues/add` 🔒 admin
- リクエスト（`VenueCreate`）: `name`、`address`、`city`、`country`（すべて str、必須）、`total_capacity`（int、>0）、
  `contact_info`（str、任意）
- レスポンス（`VenueRead`）: `id`、`size`（導出されたラベル）、`created_at` が加わる
- UI: 管理者 — 会場の作成

### `GET /venues/all` 🔓
- レスポンス: `List[VenueRead]`
- UI: 公演を作成するときの会場の選択肢

### `GET /venues/{id}` 🔓
- レスポンス: `VenueRead`
- UI: 会場の詳細（独立したページになることはまれ — 通常は公演ページ内に表示）

### `PUT /venues/update/{id}` 🔒 admin
- リクエスト（`VenueUpdate`）: 作成と同じフィールド

### `DELETE /venues/delete/{id}` 🔒 admin
- レスポンス: `{"msg": "Venue deleted successfully"}`

### `POST /concerts/add` 🔒 manager+
- リクエスト（`ConcertCreate`）: `venue_id`（uuid）、`title`（str）、`description`（str、任意）、`capacity`（int、>0）、
  `event_datetime`（datetime）、`doors_open_at`（datetime、任意）、`company_id`（uuid）
- レスポンス（`ConcertRead`）: `id`、`status`、`created_at`、`updated_at` が加わる
- UI: マネージャー — 公演の作成

### `GET /concerts/all` 🔓
- レスポンス: `List[ConcertRead]`
- UI: 公演の一覧／「今後の公演」ページ

### `GET /concerts/{id}` 🔓
- レスポンス: `ConcertRead`
- UI: 公演の詳細ページ（ページ全体を組み立てるには、`/ticket_types/concert/{id}` と下の出演者のエンドポイントと
  組み合わせる）

### `GET /concerts/events-page` 🔓
- レスポンス（`EventsPageRead`）: `concerts` — それぞれ `ConcertRead` にその `venue` が加わったもの
- エラー: 公演がなければ `404`
- UI: 公開のイベントページ

### `GET /concerts/{id}/detail` 🔓 (auth optional)
（認証は任意）
公演ページ全体を 1 回の呼び出しで。共有部分はキャッシュされ、閲覧者ごとのフィールドはリクエストごとに計算され、
ゲストでは `false`／空になる。
- レスポンス（`ConcertDetailRead`）: `concert`、`venue`、`ticket_types`、`lineup`（アイドル: `id`、`name`、
  `profile_image_url`、`color_hex`）、`performing_groups`（`id`、`name`）、`lottery_campaigns`、`direct_sale_campaigns`、
  そして閲覧者ごとの: `has_ticket`、`has_won_lottery`、`entered_campaign_ids`、`my_lottery_preferences`
- エラー: 公演が存在しなければ `404`
- レート制限: ユーザーごと、ゲストなら IP ごとに 30/分
- UI: 公演の詳細ページ — キャンペーンのリストからティアごとに「抽選に応募」か「今すぐ購入」かを選び、閲覧者ごとの
  フィールドを使ってファンが取れない操作を隠す

### `GET /concerts/manager-events-page` 🔒 manager+ (company-scoped)
- レスポンス（`ManagerEventsPageRead`）: `concerts`（`List[ConcertRead]` — マネージャーには自分の事務所のもの、
  管理者にはすべての事務所のもの）、`venues`（`List[VenueRead]`、すべての会場 — 会場は共有）
- エラー: トークンなしなら `401`、ファンなら `403`
- UI: マネージャー — 公演のテーブルと作成フォーム

### `PUT /concerts/update/{id}` 🔒 manager+ (company-scoped)
- リクエスト（`ConcertUpdate`）: 作成と同じ、加えて `status`（str、任意）
- UI: マネージャー — 公演の編集

### `DELETE /concerts/delete/{id}` 🔒 manager+ (company-scoped)
- レスポンス: `{"msg": "Concert deleted successfully"}`

### `POST /concerts/performers/assign` 🔒 manager+
アイドルまたはグループを公演の出演者として紐づける。
- リクエスト（`ConcertPerformerAssign`）: `concert_id`（uuid）、`idol_id`（uuid、任意）、`group_id`（uuid、任意）—
  実際には `idol_id`/`group_id` のちょうど一方
- レスポンス（`ConcertPerformerRead`）: `id` が加わる
- UI: マネージャー — 公演の編集、「ラインナップ」のセクション

### `GET /concerts/performers/concert/{concert_id}` 🔓
- レスポンス: `List[ConcertPerformerRead]`
- UI: 公演の詳細ページ — ラインナップの一覧

### `GET /concerts/performers/all` 🔓
フロントエンドでは未使用。
- レスポンス: `List[ConcertPerformerRead]`
- エラー: 出演者のいる公演がなければ `404`

### `DELETE /concerts/performers/{id}` 🔒 manager+
- レスポンス: `{"msg": "Performer unassigned from concert successfully"}`
- UI: マネージャー — ラインナップの項目の削除

### `PUT /concerts/lottery-draw/{id}` 🔒 manager+ (company-scoped)
1 つの公演のすべてのティアについて抽選を実行する。リクエストはそれを予約するだけ: 抽選は Celery ワーカーで実行
され、公演の事務所のマネージャーは今 `lottery_draw_triggered` を、終わったときに `lottery_draw_completed` または
`lottery_draw_failed` を受け取る（§7）。ファンは `lottery_result` 通知を受け取り、当選者は
`POST /tickets/{ticket_id}/checkout` で支払う `pending_payment` のチケットを得る。
- レスポンス: `200 {"msg": "Lottery draw task has been scheduled. ..."}` — 抽選が後で失敗した場合（受付がまだ終わって
  いない、抽選するものが残っていない）でも返される。結果は通知か `GET /lottery_entries/concert/{concert_id}/results` で
  確認すること
- エラー: マネージャーの事務所の外なら `403`、未知の公演なら `404`
- UI: マネージャー — 公演の編集ページの「抽選を実行」ボタン。受付が終わるまで無効にしておく

### `POST /ticket_types/add` 🔒 manager+
公演の券種のティア（例:「VIP」、「一般」）— `sale_method` によって、抽選で販売するか、（実装されれば —
`project_status_JP.md` §5 を参照）直接購入で販売するかが決まる。
- リクエスト（`TicketTypeCreate`）: `tier`（str）、`price`（float、≥0）、`total_quantity`（int、≥0）、`sale_method`（str、
  デフォルト `"lottery"`）、`concert_id`（uuid）
- レスポンス（`TicketTypeRead`）: `id`、`sold_quantity`、`created_at` が加わる
- UI: マネージャー — 公演の編集、「券種のティア」のセクション

### `GET /ticket_types/concert/{concert_id}` 🔓
- レスポンス: `List[TicketTypeRead]`
- UI: 公演の詳細ページ — 券種のティアの一覧（価格、残数 = `total_quantity - sold_quantity`）

### `GET /ticket_types/{id}` 🔓
- レスポンス: `TicketTypeRead`
- UI: 券種のティアの詳細／抽選応募の確認ステップ

### `PUT /ticket_types/update/{id}` 🔒 manager+
- リクエスト（`TicketTypeUpdate`）: `price`（任意）、`total_quantity`（任意）— 作成後に編集できるのはこの 2 つだけ
- UI: マネージャー — 券種のティアの編集

### `DELETE /ticket_types/delete/{id}` 🔒 manager+
- レスポンス: `{"msg": "Ticket type deleted successfully"}`

### `POST /lottery_campaigns/add` 🔒 manager+
- リクエスト（`LotteryCampaignCreate`）: `entry_start_at`、`entry_end_at`（どちらも datetime）、`payment_deadline_hours`
  （int、デフォルト 48）、`ticket_type_id`（uuid）。`max_entries_per_user` は受け付けない（送られても無視される）—
  今のところサーバー側で 1 に固定されている。
- レスポンス（`LotteryCampaignRead`）: `id`、`status`、`max_entries_per_user`（読み取り専用、今のところ常に 1）、
  `draw_at`（実際に抽選されるまで null — 抽選ジョブだけが書き込み、クライアントが指定することはない）、`created_at` が
  加わる
- UI: マネージャー — 券種のティアの抽選を設定する

### `GET /lottery_campaigns/ticket_type/{ticket_type_id}` 🔓
- レスポンス: `List[LotteryCampaignRead]`
- UI: 券種のティアのページ — キャンペーンが open なら「この抽選に応募」

### `GET /lottery_campaigns/{id}` 🔓
- レスポンス: `LotteryCampaignRead`
- UI: 抽選の応募ページ

### `PUT /lottery_campaigns/update/{id}` 🔒 manager+
- リクエスト（`LotteryCampaignUpdate`）: 作成と同じ、加えて `status`（任意）

### `DELETE /lottery_campaigns/delete/{id}` 🔒 manager+
- レスポンス: `{"msg": "Lottery campaign deleted successfully"}`

### `POST /direct_sale_campaigns/add` 🔒 manager+ (company-scoped)
`sale_method="direct"` の券種の販売期間（`database-design_JP.md` §3.21）。一般販売のティアは、そのキャンペーンの
いずれかが `open` で、現在時刻が期間内にある間だけ購入できる。
- リクエスト（`DirectSaleCampaignCreate`）: `ticket_type_id`（uuid、一般販売のティアでなければならない）、
  `sale_start_at`、`sale_end_at`（datetime、終了は開始より後）
- レスポンス（`DirectSaleCampaignRead`）: `id`、`status`（`open` | `cancelled`）、`created_at` が加わる
- エラー: 抽選の券種なら `400`、マネージャーの事務所の外なら `403`、未知の券種なら `404`、期間が逆転していれば `422`
- UI: マネージャー — 公演の編集ページの「このティアを販売する」

### `GET /direct_sale_campaigns/ticket_type/{ticket_type_id}` 🔓
フロントエンドでは未使用（公演の詳細ページにすでにキャンペーンが含まれている）。
- レスポンス: `List[DirectSaleCampaignRead]`
- エラー: 券種にキャンペーンがなければ `404`

### `GET /direct_sale_campaigns/{id}` 🔓
フロントエンドでは未使用。
- レスポンス: `DirectSaleCampaignRead`

### `PUT /direct_sale_campaigns/update/{id}` 🔒 manager+ (company-scoped)
フロントエンドでは未使用。
- リクエスト（`DirectSaleCampaignUpdate`）: `sale_start_at`、`sale_end_at`（どちらも必須）、`status`（任意 —
  `cancelled` で販売を早めに止める）
- レスポンス: `DirectSaleCampaignRead`

### `DELETE /direct_sale_campaigns/delete/{id}` 🔒 manager+ (company-scoped)
フロントエンドでは未使用。
- レスポンス: `{"msg": "Direct sale campaign deleted successfully"}`

### `POST /lottery_entries/apply` 🔒 fan
抽選キャンペーンに応募する。サービス層のチェックと DB トリガーの両方で強制される（上限と — `project_status_JP.md`
§4 の項目 9 を参照 — 希望の必須チェック）。トリガー違反は 500 ではなく通常の HTTP エラーとして表面化する。
- リクエスト（`LotteryEntryApply`）: `campaign_id`（uuid）
- レスポンス（`LotteryEntryRead`）: `id`、`campaign_id`、`user_id`、`status`、`created_at`、`drawn_at`
- エラー: `400` は、下の上限／希望なしのケースだけでなく、この公演の有効なチケット（一般販売で購入、または先のティアで
  当選）をすでに持っているファンもカバーする — `"You already hold a ticket for this concert"`
- UI: 抽選の応募ページの「応募」ボタン — ファンがすでに応募した、すでにその公演のチケットを持っている、または
  `entry_end_at` を過ぎたら、無効化／非表示にする

### `POST /lottery_entries/apply-batch` 🔒 fan
1 回のリクエストで公演の複数のティアに応募する — すべての応募が作成されるか、1 つも作成されないかのどちらかで、
レート制限の枠は 1 つだけ使う（3/分）。
- リクエスト（`LotteryEntryApplyBatch`）: `campaign_ids`（uuid のリスト、1〜10 件、重複なし）
- レスポンス: `List[LotteryEntryRead]`
- エラー: `/apply` と同じで、最初に失敗したキャンペーンのもの
- UI: 公演ページ —「順位を付けたすべてのティアに応募」ボタン

### `GET /lottery_entries/mine` 🔒 fan
- レスポンス: `List[LotteryEntryRead]`
- UI:「抽選の応募履歴」ページ — `status`（pending/won/lost）と `drawn_at` を表示する

### `GET /lottery_entries/campaign/{campaign_id}` 🔒 manager+
- レスポンス: `List[LotteryEntryRead]`
- UI: マネージャー — キャンペーンの応募者を確認する（抽選前、または抽選後の監査）

### `GET /lottery_entries/concert/{concert_id}/results` 🔒 manager+
公演全体の抽選結果を一度に（すべての券種のティアのキャンペーンをまとめて。抽選自体の公演単位の粒度と一致する —
`PUT /concerts/lottery-draw/{id}` を参照）。上の `/campaign/{campaign_id}` のような生の応募の行ではない: 決着した
（`won`/`lost`）応募だけで、それぞれにすでに当選者のメールアドレスと、当選者についてはチケットの支払い状況がまとめ
られている — 当選者ごとに 2 回目のリクエストは不要。
- レスポンス（`List[LotteryDrawResultRead]`）: `lottery_entry_id`、`user_id`、`email`、`ticket_type_id`、`tier`、
  `status`（`won`|`lost` のみ）、`drawn_at`、`ticket_id`、`payment_status`、`payment_deadline_at` — 最後の 3 つは
  `lost` の行では `null`（チケットは発行されていない）
- 公演にまだ決着した応募がなければ（「まったく抽選されていない」を含む）`[]` を返す
- エラー: `404`（未知の公演）、`403`（他の事務所の公演）
- UI: マネージャー — 公演の抽選後の結果テーブル／エクスポート。`lottery_draw_completed`/`lottery_draw_failed` の
  通知が届いた後にポーリングまたは更新する（`project_status_JP.md` §8 を参照）

### `POST /lottery_preferences/set` 🔒 fan
ファンが受け入れる券種のティア（1 つの公演内）に優先順位を付ける — 一部の抽選に応募する前に必要（上のトリガーの
注記を参照）。
- リクエスト（`LotteryPreferenceSet`）: `concert_id`（uuid）、`ticket_type_ids_in_order`（list[uuid]、最低 1 件 — 並び順が
  順位）
- レスポンス: `List[LotteryPreferenceRead]`（`id`、`concert_id`、`user_id`、`ticket_type_id`、`rank`、`created_at`）
- UI: 抽選前の「希望するティアに順位を付ける」ステップ。公演の券種をドラッグで並べ替えるリスト

### `GET /lottery_preferences/mine/{concert_id}` 🔒 fan
- レスポンス: `List[LotteryPreferenceRead]`
- UI: 同じページで、既存の順位付けを表示／編集する

### `DELETE /lottery_preferences/mine/{concert_id}` 🔒 fan
その公演についてのファンの順位付けをクリアする。
- レスポンス: `{"msg": "Preferences cleared successfully"}`
- UI:「順位付けをクリア」のコントロール

### `POST /tickets/checkout` 🔒 fan
`sale_method="direct"` の券種のティアを直接購入する — 抽選なし。そのティアに、現在時刻を含む期間の `open` な一般
販売キャンペーンがある間だけ（上の `Direct Sale Campaigns` を参照）。
- リクエスト（`TicketCheckoutCreate`）: `ticket_type_id`（uuid、`sale_method="direct"` でなければならない）、`amount`、
  `gateway`、`simulate_succ`、`idempotency_key` — `POST /order/checkout` の決済フィールドと同じ形。`amount` は税込みの
  ティアの価格と等しくなければならない。`gateway="paypal"` の場合、チケットと決済は `pending` で作成される。
  `GET /payment/status/ticket/{ticket_id}` から `pg_approval_url` を読む — §6 の PayPal のフローを参照。
- レスポンス（`TicketRead`）
- エラー: `400` は、とりわけ、この公演に未解決の抽選応募を持つファンをカバーする — 同じ公演の *別の* ティアに対する
  そのファンの `lottery_entries` がまだ `pending` または `won` なら、一般販売での購入はブロックされる（`"You have a
  pending or won lottery application for this concert — resolve it before buying a direct-sale ticket"`）。これを解消する
  のは `lost` の応募（または応募なし）だけ。「この公演の有効なチケットをすでに持っている」
  （`trg_tickets_one_per_concert`）、販売期間外、売り切れ、金額の不一致も `400`。
- UI: 一般販売のチケット購入ページ — 抽選との衝突のエラーは区別して表示すること。「この公演の抽選でまだ結果待ちです」
  は「売り切れ」とは別のメッセージである

### `POST /tickets/{ticket_id}/checkout` 🔒 fan
抽選で当選したチケット（抽選によって作成された、ステータス `pending_payment` のもの）の代金を支払う。
- リクエスト（`WonTicketCheckoutCreate`）: `amount`（int、税込みのティアの価格）、`gateway`（`mock` | `paypal`）、
  `simulate_succ`（mock のみ）、`idempotency_key`
- レスポンス: `TicketRead`
- エラー: チケットが呼び出し元のものでなければ `404`。支払い可能な抽選当選チケットでない、金額が一致しない、
  ゲートウェイが未対応、または `payment_deadline_at` を過ぎている（その場合チケットは `expired` になり、席は解放
  される）なら `400`。冪等性キーが再利用されていれば `409`
- UI:「マイチケット」／抽選結果のページ — 期限前の「今すぐ支払う」

### `POST /tickets/add` 🔒 admin
手動発行 — サポート／テスト用のツール。通常のチケットは抽選（`PUT /concerts/lottery-draw/{id}`）または一般販売の
購入（`POST /tickets/checkout`）から生まれる。受取人は、その公演の有効なチケットを持っていないファンでなければ
ならない。
- リクエスト（`TicketCreate`）: `ticket_type_id`（uuid）、`user_id`（uuid）、`lottery_entry_id`（uuid、任意 — 当選した
  応募への紐づけ）
- レスポンス（`TicketRead`）: `id`、`payment_id`、`status`、`issued_code`、`reserved_at`、`payment_deadline_at`、
  `created_at`、`updated_at` が加わる
- UI: 管理者 — チケットの手動発行ツール

### `GET /tickets/mine` 🔒 fan
- レスポンス: `List[TicketRead]`
- UI:「マイチケット」ページ

### `GET /tickets/{id}` 🔒 fan
- レスポンス: `TicketRead`
- UI: チケットの詳細（例: `issued_code` を QR／バーコードのペイロードとして表示する）

### `GET /tickets/concert/{concert_id}/sales` 🔒 manager+ (company-scoped)
フロントエンドでは未使用。
- リクエスト: クエリパラメータ `page`（デフォルト 1）、`limit`（デフォルト 10、最大 50）
- レスポンス（`TicketSalesPageRead`）: `ticket_id`、`tier`、`status`、`price`、`source`（`lottery` | `direct`）、
  `created_at` のページ分けされた `data`
- エラー: マネージャーの事務所の外なら `403`、未知の公演なら `404`

### `PUT /tickets/update/{id}` 🔒 admin
- リクエスト（`TicketUpdate`）: `status`、`issued_code`、`payment_id`、`payment_deadline_at`（すべて任意）
- UI: 管理者 — チケットのレコードの編集

### `DELETE /tickets/delete/{id}` 🔒 admin
- レスポンス: `{"msg": "Ticket deleted successfully"}`

---

## 5. マーケットプレイス — 商品、カテゴリ、アルバム／グッズの詳細、ジャンル

### `POST /categories/add` 🔒 admin
- リクエスト（`CategoryBase`）: `name`（str、1〜100 文字）
- レスポンス: `{"msg": "Category added successfully"}` — 作成されたカテゴリでは **ない**。`id` を得るには
  `/categories/all` を再取得する
- UI: 管理者 — カテゴリのカタログ

### `GET /categories/all` 🔓
- レスポンス: `List[CategoryRead]`（`id`、`name`、`is_resale_capped`）
- UI: グッズのカタログページのカテゴリのフィルタ／ナビゲーション。商品フォームのカテゴリの選択肢

### `PUT /categories/update` 🔒 admin
注: ここでは `id` はパスのセグメントではなくクエリパラメータ。
- リクエスト: クエリパラメータ `id`（uuid）+ ボディ（`CategoryUpdate`）: `name`、`is_resale_capped`（任意）
- レスポンス: `{"msg": "Category updated successfully"}`

### `DELETE /categories/delete/{id}` 🔒 admin
- レスポンス: `{"msg": "Category deleted successfully"}`

### `GET /products/all` 🔓
- レスポンス: `List[ProductRead]`（`id`、`name`、`price`、`description`、`quantity`、`image_url`、`category` — ID では
  なく、カテゴリの *名前* の文字列）
- UI: グッズのカタログのグリッド

### `GET /products/store-page` 🔓
- レスポンス（`StorePageRead`）: `products`（`List[ProductCard]`）、`groups`（`id`、`name` — アーティストのフィルタ用）。
  `ProductCard` は `id`、`name`、`price`、`description`、`quantity`、`image_url`、`category`（名前）、`album`（アルバムの
  詳細または `null`）、`genres`、`artist`（クレジットされているアイドル／グループまたは `null`）、`resale_cap_quantity`
  （ファンごとの生涯の上限。カテゴリに上限がなければ `null`）
- エラー: 商品がなければ `404`
- UI: ストアページ

### `GET /products/{id}/detail` 🔓
- レスポンス（`ProductDetailRead`）: `product`（`ProductCard`）、`recommendations`（`List[ProductCard]`）
- エラー: 商品が存在しなければ `404`
- UI: 商品の詳細ページ

### `GET /products/manager-products-page` 🔒 manager+ (company-scoped)
- リクエスト: クエリパラメータ `company_id`（uuid、任意、**管理者のみ** — マネージャーは常に自分の事務所のものを
  受け取り、パラメータは無視される。管理者が省略するとすべての商品を受け取る）
- レスポンス（`ManagerProductsPageRead`）: `products`（`List[ProductRead]`）— その事務所の商品と、所有者のない商品
  （アルバム／グッズの詳細なし）
- エラー: トークンなしなら `401`、ファンなら `403`
- UI: マネージャー — 商品のテーブル

### `GET /products/manager-product-form-page` 🔒 manager+ (company-scoped)
- リクエスト: クエリパラメータ `company_id`（uuid、任意、**管理者のみ** — 上と同じ）
- レスポンス（`ManagerProductFormPageRead`）: `products`（上と同じスコープ）、`categories`、`idols`、`groups`、`colors` —
  作成／編集フォームの選択肢に必要なものすべて。マネージャーの場合、`idols` と `groups` は自分の事務所のもの。
  管理者はすべての事務所のものを受け取る。`categories`/`colors` は共有
- エラー: トークンなしなら `401`、ファンなら `403`
- UI: マネージャー — 商品の作成／編集フォーム

### `GET /products/{id}/sales` 🔒 manager+ (company-scoped)
- リクエスト: クエリパラメータ `page`（デフォルト 1）、`limit`（デフォルト 10、最大 50）
- レスポンス（`ProductSalesPageRead`）: `order_id`、`order_status`、`order_created_at`、`quantity`、`price`、
  `line_total` のページ分けされた `data`
- エラー: マネージャーの事務所の外なら `403`、未知の商品なら `404`
- UI: マネージャー — 商品ごとの販売テーブル

### `GET /products/search/{id}` 🔓
フロントエンドでは未使用（`GET /products/{id}/detail` を使う）。
- レスポンス（`ProductWithCategoryRead`）: `id`、`name`、`price`、`description`、`quantity`、`image_url`、`category`
  （完全な `CategoryRead` オブジェクト）

### `GET /products/pagination` 🔓
- リクエスト: クエリパラメータ `page`（int、デフォルト 1）、`limit`（int、デフォルト 10、最大 50）
- レスポンス: `{"page", "limit", "count", "data": [Product...]}` — 本当のページネーションを持つ唯一のエンドポイント。
  メインのカタログページには `/all` よりこちらを優先する
- UI: グッズのカタログのグリッド、ページ分けあり

### `GET /products/filter` 🔓
- リクエスト: クエリパラメータ `category`（str、必須）、`name`（str、任意）、`min_price`（int、任意）、`max_price`
  （int、任意）、`limit`/`page`（上と同じ）
- レスポンス: `/pagination` と同じ形
- UI: フィルタ／検索を適用したグッズのカタログ

### `POST /products/add_product` 🔒 manager+ — **multipart/form-data**, not JSON
（JSON ではなく **multipart/form-data**）
- リクエスト（フォームのフィールド）: `name`（str）、`price`（float）、`description`（str）、`quantity`（int）、
  `category_id`（uuid）、`image`（ファイル、任意、アイドルの画像と同じ制約）
- レスポンス: `{"msg": "Product added successfully"}` — 新しい商品の `id` を得るには再取得する
- UI: マネージャー — 商品の作成。作成時には意図的にどの事務所にもスコープされない（`project_status_JP.md` §4 の
  項目 10 を参照）— 素の商品は、アルバム／グッズの詳細が紐づけられる（下記）まで、アイドル／グループとの結びつきを
  持たない

### `POST /products/add_with_detail` 🔒 manager+ (company-scoped) — **multipart/form-data**
商品とそのアルバムまたはグッズの詳細の行を 1 つのトランザクションで作成するので、商品が所有者なしのまま残ることは
ない。マネージャーの商品フォームが使うのはこれ。
- リクエスト（フォームのフィールド）: `add_product` のフィールド（`name`、`price`、`description`、`quantity`、
  `category_id`、`image`）に加えて、`detail_kind`（`album` | `merch`）、`idol_id`/`group_id`（アルバム: 少なくとも
  一方、グッズ: ちょうど一方）、アルバムのみの `release_date`、`track_count`、`format`（デフォルト `physical`）、
  グッズのみの `edition`、`color_id`
- レスポンス: `{"msg": "Product added successfully"}`
- エラー: 不正なフィールドの組み合わせなら `422`、拒否された画像なら `400`、マネージャーの事務所の外のアイドル／
  グループなら `403`

### `PUT /products/update/{id}` 🔒 manager+ — **company-scoped once the product has album/merch details attached**
（**アルバム／グッズの詳細が紐づけられた後は事務所スコープあり**）
- リクエスト（`ProductCreate`）: `name`、`price`、`description`、`quantity`、`image_url`、`category_id`
- レスポンス: `{"msg": "Product Updated successfully"}` — `category_id` が既存のカテゴリを参照していなければ `400`
  （`project_status_JP.md` の項目 13）
- UI: マネージャー — 商品の編集。商品が（アルバム／グッズの詳細を通じて）マネージャーとは別の事務所に紐づいていれば
  `403`

### `POST /products/{id}/image` 🔒 manager+ (same company-scoping as update)
（更新と同じ事務所スコープ）
商品の画像だけを置き換える。
- リクエスト: `multipart/form-data`、`image`（ファイル、必須）
- レスポンス: `{"msg": "Product image updated successfully"}`
- UI: マネージャー — 商品の編集、「写真を変更」

### `DELETE /products/delete/{id}` 🔒 manager+ (same company-scoping as update)
（更新と同じ事務所スコープ）
- レスポンス: `{"detail": "Product Deleted successfully"}` — この一覧の他のすべての削除のエンドポイントと違い、キーが
  `msg` ではなく `detail` であることに注意

### `POST /products/bulk_products` 🔒 manager+
- リクエスト: `List[ProductCreate]`（JSON の配列。各項目に `category_id` が必要 — 一括では画像をサポートしない）
- レスポンス: `{"msg": "<n> bulk products added successfully"}`
- UI: マネージャー — CSV／一括インポートのツール（作るなら）

### `POST /album_details/add` 🔒 manager+
既存の商品にアルバム固有のデータを紐づけるもので、これがその商品の事務所の所有関係を確立する。
- リクエスト（`AlbumDetailCreate`）: `product_id`（uuid、すでに存在していなければならない）、`idol_id`（uuid、任意）、
  `group_id`（uuid、任意 — 2 つのうちちょうど一方が必須）、`release_date`（date、任意）、`track_count`（int、任意、
  >0）、`format`（str、デフォルト `"physical"`）— ここにはジャケット画像のフィールドはない。アルバムかどうかに
  かかわらず、すべての商品の画像は `products.image_url` だけである（`POST /products/{id}/image`）。
  `database-design_JP.md` §3.16 を参照
- レスポンス（`AlbumDetailRead`）: `product_id`、`idol_id`、`group_id`、加えて基本のフィールド
- 参照している `idol_id`/`group_id` が無効化されている（`is_active=false`）なら `400` — 無効なアーティストに新しい
  リリースを紐づけることはできない（database-design_JP.md §3.3/§3.4）
- UI: マネージャー — 商品フォームの「これはアルバム」のトグルで、これらのフィールドを表示する

### `GET /album_details/all` 🔓
- レスポンス: `List[AlbumDetailRead]`
- UI: グッズのカタログ — アルバム固有のバッジ／フィルタ

### `GET /album_details/{product_id}` 🔓
- レスポンス: `AlbumDetailRead`
- UI: 商品の詳細ページ（アルバム版）

### `PUT /album_details/update/{product_id}` 🔒 manager+ (company-scoped)
- リクエスト（`AlbumDetailUpdate`）: `release_date`、`track_count`、`format`（`idol_id`/`group_id` は作成後に変更
  できない）

### `DELETE /album_details/delete/{product_id}` 🔒 manager+ (company-scoped)
- レスポンス: `{"msg": "Album details deleted successfully"}`

### `POST /genres/add` 🔒 manager+
- リクエスト（`GenreCreate`）: `name`（str、1〜100 文字）
- レスポンス（`GenreRead`）: `id` が加わる
- UI: マネージャー — ジャンルのカタログ（共有、事務所ごとではない）

### `GET /genres/all` 🔓
- レスポンス: `List[GenreRead]`
- UI: アルバムの編集フォームのジャンルの選択肢

### `DELETE /genres/delete/{id}` 🔒 admin
- レスポンス: `{"msg": "Genre deleted successfully"}`

### `POST /genres/album_genres/assign` 🔒 manager+
- リクエスト（`AlbumGenreAssign`）: `product_id`（uuid）、`genre_id`（uuid）
- レスポンス（`AlbumGenreRead`）: `product_id`、`genre_id`
- UI: アルバムの編集ページ —「ジャンル」の複数選択

### `GET /genres/album_genres/album/{product_id}` 🔓
- レスポンス: `List[AlbumGenreRead]`
- UI: アルバムの詳細ページ — ジャンルのタグ

### `GET /genres/album_genres/all` 🔓
フロントエンドでは未使用。
- レスポンス: `List[AlbumGenreRead]`（`product_id`、`genre_id`）
- エラー: ジャンルを持つアルバムがなければ `404`

### `DELETE /genres/album_genres/{product_id}/{genre_id}` 🔒 manager+
- レスポンス: `{"msg": "Genre unassigned from album successfully"}`
- UI: アルバムの編集ページ — ジャンルのタグの削除

### `POST /merch_details/add` 🔒 manager+
アルバムの詳細と同じパターンで、1 人のアイドルまたは 1 つのグループに紐づく公式グッズのためのもの — ペンライト、
ツアーパーカー、1 つの明確な看板のもとで販売されるものなら何でも。（元は `/lightstick_details/*` でペンライトだけに
スコープされていた。`Lightstick` カテゴリが `Merch` に統合されたときに一般化した — `database-design_JP.md`
§3.15/§3.17 を参照。リクエスト／レスポンスのフィールドの形は改名前から変わっていない。）
- リクエスト（`MerchDetailCreate`）: `product_id`（uuid）、`idol_id`（uuid、任意）、`group_id`（uuid、任意 — ちょうど
  一方）、`edition`（str、任意）、`color_id`（uuid、任意 — `idol_colors` への紐づけ）
- レスポンス（`MerchDetailRead`）: `created_at` が加わる
- 参照している `idol_id`/`group_id` が無効化されている（`is_active=false`）なら `400` — `POST /album_details/add` と
  同じルール
- UI: マネージャー — 商品フォームで所有者を紐づける（これがペンライトだけでなくあらゆるブランドのグッズをカバーする
  ようになった今、ペンライト固有のトグルはもう意味をなさない）

### `GET /merch_details/all` 🔓
- レスポンス: `List[MerchDetailRead]`

### `GET /merch_details/{product_id}` 🔓
- レスポンス: `MerchDetailRead`
- UI: 商品の詳細ページ（グッズ版）

### `PUT /merch_details/update/{product_id}` 🔒 manager+ (company-scoped)
- リクエスト（`MerchDetailUpdate`）: `edition`、`color_id`

### `DELETE /merch_details/delete/{product_id}` 🔒 manager+ (company-scoped)
- レスポンス: `{"msg": "Merch details deleted successfully"}`

---

## 6. ショッピング — カート、配送、注文、決済

### `POST /cart/add_cart` 🔒 fan
- リクエスト（`CartItem`）: `product_id`（uuid）、`quantity`（int、≥1）
- レスポンス: スキーマで強制されていない。生の `Cart` の行（`id`、`product_id`、`quantity`、`user_id`、`price`、
  `total_price`）— すでにカートにある商品を追加すると、重複した行を作るのではなく数量が増える
- UI: 商品が表示されるあらゆる場所の「カートに追加」ボタン

### `GET /cart/see_cart` 🔒 fan
- レスポンス: スキーマで強制されていない。`{"items": [Cart...], "total_price": float}`
- UI: カートページ／カートのドロワー

### `DELETE /cart/delete_cart/{cart_id}` 🔒 fan
`cart_id` は商品の ID ではなく、カートの行の ID（`see_cart` の `items` から）。
- レスポンス: `{"msg": "Cart item deleted successfully"}`
- UI: カートページ — 商品の削除

### `POST /shipping_addresses/add` 🔒 fan
- リクエスト（`ShippingBase`）: `address_line1`（str）、`address_line2`（str、任意）、`city`（str）、`postal_code`
  （int — **注意:** 整数型なので、英国／カナダの形式のような英数字の郵便番号は正しく保存できない。
  `project_status_JP.md` §4 の項目 5 を参照）、`state`（str）、`country`（str）
- レスポンス（`ShippingAddress`）: `id`、`user_id` が加わる
- UI: 購入手続き —「新しい住所を追加」、およびアカウント設定

### `GET /shipping_addresses/fetch` 🔒 fan
- レスポンス: `List[ShippingAddress]`
- UI: 購入手続き — 保存済みの住所の選択肢。アカウント設定 — 住所の一覧

### `GET /shipping_addresses/fetch_byid/{address_id}` 🔒 fan
- レスポンス: `ShippingAddress` — 呼び出し元自身の住所のみ。他人の ID は `404`
- UI: 住所の詳細／編集フォームの初期値

### `PUT /shipping_addresses/update/{address_id}` 🔒 fan
- リクエスト（`ShippingBase`）: 追加と同じフィールド
- レスポンス: `{"msg": "Address updated successfully"}`

### `DELETE /shipping_addresses/delete/{address_id}` 🔒 fan
- レスポンス: `{"msg": "Address deleted successfully"}`

### `POST /order/checkout` 🔒 fan
1 回の呼び出しでカートを注文と決済に変換する。**レスポンスは決済ではなく `Order`** — それ自体は
`payment_id`/`pg_order_id` を持たないので、`gateway="paypal"` の購入手続きでは、続けて
`GET /payment/status/order/{order_id}`（下記）を呼んで決済とその `pg_approval_url` を取得しなければならない。
リダイレクトの流れ全体は下の「PayPal の購入フロー」を参照。
- リクエスト（`PaymentCreate`）: `amount`（int — カートの現在の合計と等しくなければならず、サーバー側でチェック
  される）、`shipping_address_id`（uuid）、`gateway`（`"mock"` | `"paypal"`、デフォルト `"mock"`）、`simulate_succ`
  （bool、任意 — モックゲートウェイのみで、モックの成功／失敗を強制する）、`idempotency_key`（uuid、**必須** — 購入の
  試行ごとに新しいものを生成する。すでに決着した決済に対して同じキーで再試行すると、重複した注文ではなく `409` が
  返る）
- レスポンス（`Order`）: `id`、`user_id`、`shipping_address_id`、`total_price`、`status`
  （`"pending"|"confirmed"|"cancelled"` — `paypal` の購入手続きは、決済がキャプチャされるまで `"confirmed"` ではなく
  `"pending"` で返ってくる）、`created_at`、`items`、`shippingstatus`（常に存在する — すべての注文は、後から遅延して
  作成されるのではなく、同じ購入手続きのトランザクションで `"pending"` の `shipping_status` 行を得る）、
  `shippingaddress`
- エラー: `404`（`cart_empty` / `address_not_found`）、`400`（`insufficient_stock`、`amount_mismatch`、
  `unsupported_gateway`、`resale_cap_exceeded`）、`403`（`fan_only_purchase`）、`409`（`duplicate_idempotency_key`）。
  拒否されたモック決済はエラーでは **ない**: `status: "cancelled"` とともに `200` — 汎用的な「購入に失敗しました」を
  1 つ表示するのではなく、UI でこれらを区別すること
- UI: 購入手続きのページの最後の「注文を確定」の操作

### `GET /order/fetch_placed_order` 🔒 fan
- レスポンス: `List[Order]` — 各 `Order` は `status`（`"pending"|"confirmed"|"cancelled"`）、ネストした `items`
  （`OrderItem[]`）、`shippingstatus`、`shippingaddress` を含む
- UI:「注文履歴」の一覧

### `GET /order/single_placed_order/{order_id}` 🔒 fan
- レスポンス: `Order`
- UI: 注文の詳細ページ

### `PATCH /order/cancel/{order_id}` 🔒 fan
- レスポンス: `Order`（更新後）— 注文がすでに発送されていれば `400`
- UI: 注文の詳細ページ —「注文をキャンセル」ボタン

### `GET /order/shipping_status/{order_id}` 🔒 fan
- レスポンス: スキーマで強制されていない（生の `shipping_status` の行）。`ShippingStatusResponse` の形 — `status`、
  `updated_at`（`status` が最後に変わった時刻）
- UI: 注文の詳細ページ — 配送の追跡

### `PATCH /order/update_shipping_status/{order_id}` 🔒 admin
自由な上書き — 後戻りを含め、任意のステータスを設定できる。日常の発送処理の経路ではなく、手動の修正ツールである。
そちらは下の `PATCH /order/{order_id}/ship` を参照。
- リクエスト（`ShippingStatus` enum）: `"pending" | "processing" | "shipped" | "delivered" | "cancelled"`
- レスポンス: スキーマで強制されていない（型ヒントには `Order` とあるが、上の `GET` と同じ形の生の `shipping_status`
  の行 — サービスは注文ではなく `shipping_status` の行を返す）
- 注文がすでに `cancelled` なら `400`
- UI: 管理者 — 発送処理／配送のダッシュボード、手動の上書き

### `PATCH /order/{order_id}/ship` 🔒 manager+ (company-scoped)
日常の「発送済みにする」操作 — ボタン 1 つで、ステータスの選択肢はない。`pending`/`processing` → `shipped` にだけ
進める。マネージャーは、自分の事務所の商品を少なくとも 1 つ含む注文しか発送できない（管理者はスコープされない）。
ステータスの切り替えと同じコミットで、購入者に `order_shipped` のアプリ内通知を書き込む。
- レスポンス（`Order`）: 更新された注文全体で、`POST /order/checkout` のレスポンスと同じ形 —
  `shippingstatus.status` は `"shipped"` になり、`updated_at` も新しくなる
- エラー: `404`（注文が存在しない）、`403`（マネージャーの事務所の商品がこの注文にない）、`400`（注文が
  `pending`/`processing` でない — すでに発送済み／配達済み、またはキャンセル済み）
- UI: マネージャーの注文ページ — 注文の行ごと、または注文の詳細ページの「発送」ボタン

### `GET /order/manager-orders-page` 🔒 manager+ (company-scoped)
- リクエスト: クエリパラメータ `page`（デフォルト 1）、`limit`（デフォルト 10、最大 50）、`company_id`（uuid、
  管理者のみ — マネージャーは常に自分の事務所のものを受け取る）
- レスポンス（`ManagerOrdersPageRead`）: `id`、`buyer_name`、`buyer_email`、`status`、`created_at`、`items`（この事務所の
  明細と、所有者のない商品のみ）、`company_total`、`shippingstatus` のページ分けされた `data`
- UI: マネージャー — 発送待ちの注文

### `GET /payment/status/order/{order_id}` 🔒 fan
注文の決済の読み取り専用の取得。その注文の決済がない、または注文が呼び出し元のものでなければ `404`。
- レスポンス（`PaymentResponse`）: `id`、`order_id`、`ticket_id`（ここでは null — チケットの決済でのみ設定される）、
  `user_id`、`amount`、`status`（`"pending"|"success"|"failed"|"cancelled"`）、`payment_gateway`（`"mock"|"paypal"`）、
  `is_paid`、`pg_order_id`、`pg_payment_id`、`pg_signature`、`pg_approval_url`（PayPal のリダイレクトのリンク — 下記
  参照。`"mock"` の場合や決済が決着した後は常に `null`）、`created_at`、`updated_at`
- UI: 注文の詳細／購入完了ページ — 非同期のゲートウェイを待つ間、これをポーリングする

### `GET /payment/status/ticket/{ticket_id}` 🔒 fan
上と同じ `PaymentResponse` の形で、代わりに `ticket_id` で取得する（`order_id` は null、`ticket_id` が設定される）。
一般販売のチケットの購入でも同じように使う。

### `GET /payment/status/all` 🔒 fan
- レスポンス: `List[PaymentResponse]` — ファンに決済がなければ `[]`
- UI:「支払い履歴」ページ（注文とは別に表示するなら）

### PayPal checkout flow (redirect + capture)
（PayPal の購入フロー: リダイレクト + キャプチャ）

以下はすべて、`POST /order/checkout`、`POST /tickets/checkout`、または `POST /tickets/{ticket_id}/checkout` に
`gateway="paypal"` を渡した場合にのみ当てはまる。モックゲートウェイはその 1 回の呼び出しで同期的に決着するが、PayPal は
そうではない — ファンはまずアプリを離れて、PayPal のサイトで決済を承認しなければならない。

1. **購入手続き** — `gateway="paypal"` で `POST /order/checkout`（または `/tickets/checkout`）。注文／チケットは
   `"pending"` で返ってくる — エラーではなく、これは想定どおりで、止まった状態ではない。
2. **承認リンクの取得** — `GET /payment/status/order/{order_id}`（または `.../ticket/{ticket_id}`）を呼び、レスポンスから
   `pg_approval_url` を読む。
3. **ファンをリダイレクトする** — `pg_approval_url`（この API ではなく `paypal.com` のページ）へ。これは API 呼び出し
   ではなくページ全体のリダイレクトである — 他のリダイレクト型の決済フローと同じく、ファンをサードパーティの購入
   手続きに送るものとして扱う。
4. **ファンが承認し、PayPal がフロントエンドのルートへリダイレクトで戻す** —
   `{FRONTEND_BASE_URL}/payment/paypal/return`（`app/utils/paypal_client.py::create_order` で設定）。PayPal はクエリ
   パラメータとして `token`（PayPal の注文 ID — `pg_order_id` と同じ値）と `PayerID` を付ける。
5. **キャプチャ** — ステップ 4 のフロントエンドのルートが `POST /payment/paypal/capture/{pg_order_id}` を呼ぶ（`token`
   クエリパラメータを `pg_order_id` として使う）🔒 fan。レスポンスは更新された `PaymentResponse` — `status` は
   `"success"` または `"failed"` になる。
   - ここでの `404` の意味: 見つからない、すでに決着済み（例: 下の Webhook がこの呼び出しより先に処理した — これは
     表に出すべきエラーではなく、普通の競合として扱う）、または決済が呼び出し元のものではない。
6. **キャンセル**: ファンが PayPal 側で取りやめた場合、PayPal は `token` とともに
   `{FRONTEND_BASE_URL}/payment/paypal/cancel` にリダイレクトする — キャプチャの呼び出しは不要で、注文／チケットは
   単に `"pending"` のまま残る（自動ではキャンセルされない。放置された PayPal の購入手続きを掃除する処理は現在ない。
   `project_status_JP.md` を参照）。

### `POST /payment/paypal/webhook` 🔓 (PayPal signature-verified)
（PayPal の署名で検証）
**フロントエンドがこれを直接呼ぶことはない** — このエンドポイントは、PayPal 自身のサーバー間の配信のためだけに存在し、
ステップ 5 が起きなかった場合（ファンが承認後にタブを閉じた、など）に、同じ `finalize_paypal_payment` のキャプチャの
ロジックを突き合わせるための保険である。フロントエンドが実装すべきものと誤解されないよう、ここで触れているだけ
である。

## 7. 通知

WebSocket／SSE のレイヤーは存在しない — これはショートポーリングの設計である（database-design_JP.md §3.19）。
プッシュの仕組みを持たないクライアントは、一定の間隔（15〜30 秒を推奨。タブ／アプリがバックグラウンドにある間は
止める）で `GET /notifications/unread-count` をポーリングし、毎回通知の本文全体を再取得するのではなく、件数が
増えたときにだけ重い `GET /notifications/mine` を取得すべきである。

### `GET /notifications/unread-count` 🔒 fan
軽く、ポーリングされることを想定している — 上記参照。ユーザーごとに 30 リクエスト／60 秒でレート制限されており、
まともなポーリング間隔よりはるかに上である。ここでの `429` は、クライアントのポーリングが積極的すぎることを意味し、
ユーザーに表示すべき本当のエラーではない。
- レスポンス（`NotificationUnreadCount`）: `{"count": int}`
- UI: ナビゲーションバーの通知ベルのバッジ

### `GET /notifications/mine` 🔒 fan
- クエリ: `unread_only`（bool、デフォルト `false`）
- レスポンス: `List[NotificationRead]` — `id`、`user_id`、`type`
  （`"order_confirmation"|"order_shipped"|"ticket_confirmation"|"lottery_registered"|
  "lottery_draw_triggered"|"lottery_draw_failed"|"lottery_draw_completed"|"lottery_result"|
  "lottery_payment_reminder"|"lottery_payment_confirmation"|"event_reminder"|"password_reset"`）、
  `order_id`/`ticket_id`/`lottery_entry_id`/`concert_id`（`type` に応じてちょうど 1 つが設定される）、`status`、
  `sent_at`、`is_read`、`read_at`、`created_at`
- 何もなければ（または `unread_only` に一致するものがなければ）`[]` を返す
- UI: 通知のフィード／ドロップダウン

### `POST /notifications/{notification_id}/read` 🔒 fan
- レスポンス: `NotificationRead`（更新後）
- エラー: `404`（見つからない）、`403`（他のユーザーのもの）
- UI: クリック／閉じる操作で 1 件の通知を既読にする

### `POST /notifications/read-all` 🔒 fan
- レスポンス: `{"msg": "<n> notification(s) marked as read"}`
- UI:「すべて既読にする」の操作

## 8. お問い合わせ（contact form、お問い合わせ）

### `POST /inquiries/submit` 🔓 (auth optional)
（認証は任意）
誰でも送信できる。有効な `Authorization` ヘッダーが送られた場合、お問い合わせはそのアカウントに紐づけられる。
どちらの場合も `email` フィールドは必須。
- ボディ（`InquiryCreate`）: `email`（有効なメールアドレス）、`topic`
  （`"tickets"|"lottery"|"orders"|"payment"|"account"|"other"`）、`content`（文字列、5〜2000 文字。Unicode のコード
  ポイントで数え、長さのチェックの前に、全角スペース `U+3000` を含む前後の空白が取り除かれる）。最小が 5 なのは、
  完結した日本語の質問がとても短いことがあるため。
- `email` は通常の（半角の）文字でなければならない。全角の `＠` や文字は `422` になるので、フロントエンドは送信前に
  メールアドレスを NFKC で正規化すべきである。
- レスポンス（`InquiryCreated`）: `{"id": uuid, "msg": "Your inquiry has been received"}`
- 副作用: `email` 宛てに、トピックと参照 ID を含む確認メール（メッセージ本文は決して含めない）。直近 1 時間にすでに
  3 通の確認メールを受け取ったアドレスにはそれ以上メールが送られないが、レスポンスは引き続き `200` で、お問い合わせ
  も保存される。そのため、UI の文言でユーザーにメールを約束しないこと。
- エラー: `422`（検証: 不正なメールアドレス、未知のトピック、内容が短すぎる／長すぎる）、`429`（同じアカウント、
  ゲストなら同じ IP から、10 分あたり 3 件を超える送信。`detail` に何秒待てばよいかが書かれている）
- UI: お問い合わせページのフォーム

### `POST /inquiries/instant-answer` 🔓 (auth optional)
（認証は任意）
サイトの FAQ だけから取った AI の回答で、ユーザーがお問い合わせフォームを送信する前に表示することを想定している。
何も保存されない。ログイン中のユーザーはアカウントごとに、ゲストは IP ごとにレート制限される。
- ボディ（`InstantAnswerRequest`）: `topic`（`/inquiries/submit` と同じ値）、`content`（5〜2000 文字、
  `/inquiries/submit` と同じルール）、`lang`（`"en"` または `"ja"`、デフォルト `"en"`）。
- `lang` はどの FAQ を使うかを選ぶ: `app/content/faq.md`（`en`）または `app/content/faq.ja.md`（`ja`）。UI の現在の
  言語を送ること。回答は質問の言語で返ってくるので、`lang: "en"` でも日本語の質問には日本語の回答が返るが、`lang` を
  一致させるとサイト自身の言い回しに最も近くなる。
- レスポンス（`InstantAnswerRead`）: `{"answerable": bool, "answer": string | null}`。`answer` は `answerable` が `true`
  のときだけ設定される。
- `answerable: false` は、表示するものがないすべてのケースをカバーする: FAQ がその質問をカバーしていない、機能が
  オフになっている（`ANTHROPIC_API_KEY` がない）、または AI の呼び出しが失敗した。これは決してエラーではない。
  単にフォームを表示すること。
- エラー: `422`（検証）、`429`（10 分あたり 5 リクエストを超える）。`429` はエラーを表示するのではなく、
  `answerable: false` と同じように扱うこと。
- 数秒かかることがある。読み込み中の状態を表示し、ユーザーがそのまま送信に進めるようにすること。
- UI: お問い合わせページで、質問の入力と送信ボタンの間。回答が AI によって生成されたものであることを表示すること。
