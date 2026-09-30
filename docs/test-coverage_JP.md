# テストカバレッジレポート

[English](test-coverage.md) | 日本語

テストスイートが何をカバーしているかのスナップショットで、推定ではなく実測したものです。ある時点のレポートなので
`project_status_JP.md` とは分けています: 数値が意味のある形で動いたら、個々の数字を手で編集するのではなく、下記の
コマンドを再実行して表を更新してください。

**計測日:** 2026-09-29。`develop`（`e100b11`）とマネージャーページの認証修正をマージした後の
`refactor/add-test-coverage` 上。**結果:** 923 件成功、0 件失敗、0 件スキップ。`app/` の **行カバレッジ 94.6%**
（5,907 / 6,242 ステートメント）。`develop` の `3abc98b` 時点の 85.3%（745 テスト、6,211 ステートメント）から上昇。
以下のすべての「Before」列はこの時点を基準にしている。

## 1. 計測方法

CI の `test` ジョブ（`.github/workflows/test.yml`）と同じ方法を、ローカルで実行した:

- PostgreSQL 16 と Redis をローカルで起動し、`DATABASE_URL` は作業用のデータベースを指す。スイートがそれに直接
  触れることはない: `tests/conftest.py` がすべての接続を `<name>_test` に向け直し、`tests/integration/conftest.py` が
  セッションごとに一度、そのデータベースを削除・再作成・マイグレーション（空の状態から `alembic upgrade head`）する。
- JWT／Resend のシークレットにはダミーの値。メールを送信したり PayPal に到達したりするテストはない。
- コマンド: `pytest --cov=app --cov-report=term-missing`。

これは **行カバレッジのみ** である。ブランチカバレッジ（`--cov-branch`）は有効にしていないので、一方向にしか
実行されなかった `if` を含む行もカバー済みとして数えられる。

## 2. 合計

| スイート | テスト数 | 単独での行カバレッジ | Postgres が必要か |
|---|---:|---:|---|
| `tests/unit` | 531 | 66% | 不要（モックの `Session`、`fakeredis`） |
| `tests/integration` | 392 | — | 必要（本物の Postgres。Redis は `fakeredis`） |
| **両方** | **923** | **94.6%** | |

ルーター、実際の SQL、DB トリガーは結合テストスイートでしか実行されないため、ユニットテストスイート単独では 66% に
とどまる。2 つのスイートは補完関係にあり、どちらも単独で合計に到達することを意図していない。

## 3. パッケージ別

| パッケージ | ステートメント数 | Before | After |
|---|---:|---:|---:|
| `app/services` | 2498 | 89.4% | 96.9% |
| `app/router` | 1589 | 68.1% | 86.2% |
| `app/schema` | 887 | 98.6% | 99.5% |
| `app/db` | 541 | 100.0% | 100.0% |
| `app/cache` | 327 | 97.6% | 98.8% |
| `app/utils` | 195 | 58.5% | 85.1% |
| `app/exception` | 81 | 79.0% | 100.0% |
| `app/deps` | 48 | 100.0% | 100.0% |
| `app/config` | 40 | 100.0% | 100.0% |
| `app/tasks` | 31 | 0.0% | 100.0% |
| `app/celery_app` | 5 | 100.0% | 100.0% |
| **合計** | **6242** | **85.3%** | **94.6%** |

`app/db` と `app/schema` がほぼ 100% なのは、主にモデルとスキーマのモジュールが宣言的で、インポート時に実行される
ためである。そのカバレッジは正しさについてほとんど何も語らない。その裏にあるトリガーや制約の振る舞いこそが、以下の
結合テストがチェックしているものである。

## 4. 今回追加したものと、各スイートが証明していること

5 ポイント以上変動したファイル:

| ファイル | Before | After |
|---|---:|---:|
| `app/utils/email_sender.py` | 0.0% | 100.0% |
| `app/tasks/lottery.py` | 0.0% | 100.0% |
| `app/tasks/example.py` | 0.0% | 100.0% |
| `app/tasks/email.py` | 0.0% | 100.0% |
| `app/utils/storage.py` | 37.9% | 100.0% |
| `app/router/talent/idol.py` | 43.4% | 100.0% |
| `app/router/marketplace/products.py` | 45.8% | 99.3% |
| `app/router/talent/group.py` | 47.9% | 100.0% |
| `app/router/marketplace/shipping.py` | 57.1% | 100.0% |
| `app/exception/db_triggers.py` | 59.5% | 100.0% |
| `app/services/marketplace/order_service.py` | 60.1% | 95.9% |
| `app/services/marketplace/product_service.py` | 59.4% | 94.9% |
| `app/router/events/concert.py` | 63.2% | 97.4% |
| `app/router/events/ticket.py` | 65.5% | 90.8% |
| `app/router/marketplace/order.py` | 74.7% | 88.6% |
| `app/cache/rate_limit.py` | 82.4% | 94.1% |
| `app/services/events/ticket_service.py` | 83.4% | 94.7% |
| `app/schema/marketplace/products.py` | 91.8% | 100.0% |

### 結合テスト（特記のない限り、本物の HTTP + Postgres）

- **`events/test_won_ticket_checkout.py`**: 他の競合テストと同様に、`checkout_won_ticket` をサービスレベルで、呼び出し
  ごとに 1 つの `Session` で呼ぶ。逐次的なケース: 支払っても `sold_quantity` は変わらない（抽選がすでに席を数えている）、
  拒否された決済の後もチケットは再試行のために支払い可能なまま残る、他のファンのチケット・一般販売のチケット・
  支払い済みのチケット・誤った金額・再利用された冪等性キーは拒否される。期限を過ぎるとチケットは失効し、席を解放する。
  **競合**: 二重送信でも支払いはちょうど 1 回。同じ冪等性キーを 2 回使っても決済は 1 件だけ記録される。期限後の
  3 つの並行した試行でも席はちょうど 1 回だけ解放される（`sold_quantity` は 1 → 0 で、-1 や -2 にはならない）。
- **`marketplace/test_order_fulfillment.py`**: ファンによるキャンセル（`pending`/`processing` の間のみ、自分の注文
  のみ）、`album_details`/`merch_details` を通じて事務所でスコープされたマネージャーの発送ボタン（複数の事務所が
  混在する注文、所有者のない商品、管理者による上書き、終端ステータス）、`order_shipped` 通知、管理者による発送
  ステータスの上書き（キャンセルされた注文は復活できない）、マネージャーの注文ページ。マネージャーには自分の事務所の
  明細と合計だけが表示され、`?company_id=` でそれを広げることはできない。
- **`marketplace/test_product_management.py`**: マネージャーの事務所にスコープされた詳細付きの作成（アルバム／
  グッズ）、無効化された所有者や存在しない参照の拒否、不正な詳細の組み合わせ、一時ディレクトリへの画像アップロード、
  画像の置き換え／更新／削除のスコープ、全件成功か全件失敗かの一括追加、マネージャーページ（マネージャーが指定した
  `company_id` は無視され、自分の事務所のものが使われる。フォームページのアイドル／グループの選択肢もスコープされる）、
  販売履歴、商品詳細ページでのアーティストの解決とおすすめ。
- **`marketplace/test_shipping_addresses.py`**: ID によるすべての読み取りと書き込みでの所有権。このスイートは実際の
  IDOR を見つけた（`project_status_JP.md` §4 の項目 47、同じブランチで修正）。10 件のテストのうち 5 件は修正前の
  コードに対して失敗する。
- **`talent/test_idol_group_management.py`**: 所有者のマネージャーと管理者によるアイドル／グループの作成、更新、
  論理削除、再有効化、画像アップロード。事務所をまたぐ操作の 403。他の事務所のグループ、無効化されたグループ、未知の
  カラーの検証。無効な行が公開の読み取りから消えること。マネージャーのアイドル／グループ設定ページがそのマネージャーの
  事務所のものだけを返すこと（管理者にはすべての事務所）。
- **マネージャー設定ページ**（`test_permissions.py::test_manager_settings_page_role_gate`）: 7 つすべての
  `manager-*-page` の読み取りが、トークンなしでは 401、ファンには 403、マネージャーまたは管理者には 200 を返す。
  それぞれの事務所スコープは、そのドメインのスイート（上記と下記）でチェックしている。
- **`events/test_ticket_and_concert_endpoints.py`**: 両方のチケット購入と管理者による手動発券で、どのサービスの例外が
  どのステータスコードにマッピングされるか、`/tickets/mine`、公演詳細ページでの閲覧者ごとの表示内容（ゲスト、
  チケット保有者、他のファン）、出演者の割り当て／解除のスコープ、抽選のトリガー（Celery タスクをキューに入れ、
  マネージャーに通知する）、マネージャーのイベントページがそのマネージャーの公演だけを返すこと（会場は共有のまま）。

共有フィクスチャ: **`tests/integration/_seed.py`**（`seed`、`tests/integration/conftest.py` で登録）は行を直接挿入し、
任意のロールの JWT を発行し、逆順の一括 `DELETE` で後片付けをする。その後、Postgres の `ON DELETE CASCADE` によって、
テストが API 経由で作成した行も削除される。既存の「空のテーブルは空のリストを返す」テスト（例:
`test_idols.py::test_list_idols_empty`）は、これらのスイートの実行後も成功しており、後片付けが完全であることを
確認している。

### ユニットテスト

- **`test_tasks.py`**: 3 つの Celery タスクをプロセス内で実行する。抽選タスクについて: 成功時は JSON で安全な dict を
  返す。失敗時はロールバックし、マネージャーに通知し（公演が存在しなければそれを省略し）、再送出し、必ずセッションを
  閉じる。
- **`test_email_sender.py`**: `DEBUG` のときは送信せずに出力する。Resend のペイロード。配信の失敗はログに出され、
  送出されない。
- **`test_db_triggers.py`**: すべてのトリガー／制約のメッセージが、型付きの例外と HTTP ステータスにマッピングされる。
  `diag.message_primary` が優先される。未知の DB エラーはそのまま返される。コミット／フラッシュのヘルパーは必ず
  ロールバックする。
- **`test_storage.py`**（拡張）: ローカルバックエンドの書き込みとサイズ上限時のクリーンアップ。モックの boto3
  クライアントを使った S3 バックエンド（アップロード、サイズ上限、バケットの欠如、3 種類すべての公開 URL の形）。
  `get_storage()` によるバックエンドの選択とキャッシュ。

## 5. まだカバーされていないもの

90% 未満のファイル:

| ファイル | カバレッジ | 未実行のステートメント数 |
|---|---:|---:|
| `app/utils/paypal_client.py` | 51.7% | 28 |
| `app/router/talent/idol_color.py` | 55.3% | 21 |
| `app/router/marketplace/category.py` | 59.5% | 15 |
| `app/router/talent/position.py` | 62.1% | 25 |
| `app/router/marketplace/album_detail.py` | 64.6% | 17 |
| `app/router/marketplace/merch_detail.py` | 64.6% | 17 |
| `app/router/events/lottery_campaign.py` | 67.2% | 20 |
| `app/router/events/ticket_type.py` | 67.9% | 18 |
| `app/router/marketplace/genre.py` | 68.5% | 17 |
| `app/router/events/lottery_entry.py` | 72.2% | 15 |
| `app/router/events/direct_sale_campaign.py` | 73.8% | 16 |
| `app/router/talent/management_company.py` | 80.9% | 9 |
| `app/router/shared/inquiry.py` | 82.4% | 3 |
| `app/services/events/lottery_entry_service.py` | 83.7% | 16 |
| `app/router/marketplace/order.py` | 88.6% | 9 |

- **`paypal_client.py`**: `get_access_token`、`verify_webhook_signature`、`create_order`/`capture_order` の HTTP エラー
  の経路は PayPal の API を実際に呼び出す。これらをカバーするには `requests` のレスポンスをモックする必要がある。ここでの
  本当の検証は、`project_status_JP.md` §7 のエンドツーエンドのサンドボックス購入である。
- **小さな CRUD ルーター**（メンバーカラー、カテゴリ、ポジション、アルバム／グッズの詳細、ジャンル、キャンペーン、
  券種、抽選の応募）: サービスはユニットテストされ、ロールのゲートは結合テストされている。足りないのは主に
  `except ServiceError → HTTPException` の行で、これは今では完全にカバーされているルーターと同じパターンである。
- **`lottery_entry_service.get_draw_results_for_concert`**: 抽選結果の読み取り（14 行）には、どちらのレベルでも
  テストがない。
- **`order.py` の `checkout_order`**: `PaymentFailedError` の分岐と、コミット後の確認メール。`single_placed_order` には
  見つかった場合のテストがない。

## 6. これらの数値の限界

- カバレッジはどの行が実行されたかを示すだけで、その周りのアサーションが正しいことは示さない。§4 の発送先住所の
  IDOR がその例: どのファンでも他人の住所を削除できる状態だったのに、`shipping_service.py` はモックの `Session` を
  使ったユニットテストですでに行カバレッジ 100% だった。
- Redis はどちらのスイートでも `fakeredis` なので、レート制限とキャッシュの振る舞いは本物の Redis サーバーではなく、
  その実装に対してチェックされている。
- この実行はローカルで行った。CI は GitHub Actions 上で `postgres:16` に対して同じコマンドを実行するが、これらの数値は
  CI のアーティファクトではなく、ローカルでの実行から得たものである。
