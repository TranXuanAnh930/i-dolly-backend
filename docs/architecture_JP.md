# アーキテクチャ

[English](architecture.md) | 日本語

コードベースの構成と、新しいコードが従うべき規約です。データモデル（テーブル、RBAC、ビジネスロジック）については
`database-design_JP.md` を、完成しているものと未着手のものについては `project_status_JP.md` を参照してください。

## 1. 技術スタック

- **FastAPI** 0.122（Python 3.12）+ リクエスト／レスポンススキーマに **Pydantic v2**（2.12.4）。
- **PostgreSQL**（**SQLAlchemy 2.0** 経由、`app/db/models/*`）、マイグレーションに **Alembic 1.17** — 一本の直線的な
  チェーンで、1 マイグレーションにつき 1 つの関心事。
- キャッシュ（`app/cache/cache_service.py` + `invalidation.py`、msgpack でシリアライズ、TTL 5 分）とレート制限
  （`app/cache/rate_limit.py`、固定ウィンドウのカウンター）に **Redis**。
- **Celery**（`app/celery_app.py`）。ブローカーとリザルトバックエンドは同じ Redis インスタンスだが別の DB インデックス
  （`CELERY_BROKER_DB=1` と `REDIS_DB=0`）を使い、タスクのキーがキャッシュ／レートリミッターのキーと衝突しないように
  している。現在は抽選ジョブとすべてのトランザクションメール送信（`app/tasks/lottery.py`、`app/tasks/email.py`）を
  実行する。新しいタスクは `app/tasks/` に置き、`celery_app.py` の `include=[...]` リストに追加しなければならない —
  ここに載っていないタスクは、`@celery_app.task` でデコレートされていてもワーカーに発見されない。
- **JWT**（python-jose、HS256）: 短命なアクセストークン + `refresh_tokens` テーブルに保存する不透明な UUID の
  リフレッシュトークン。ログイン／リフレッシュのたびにローテーションし、`httponly/secure/samesite=none` の Cookie で
  渡す。`samesite=none` なのはフロントエンドと API が別オリジンにあるため — `Lax` の Cookie ではクロスサイトの
  リフレッシュ呼び出しで送られない。別のシークレット（`JWT_EMAIL_SECRET_KEY`）でメール認証／パスワードリセットの
  トークンを署名し、`type` クレームで区別することで、一方をもう一方として再利用できないようにしている。
- パスワードのハッシュ化に passlib 経由の **bcrypt**。
- `mock` 決済ゲートウェイ（`PaymentGateway.mock`、`simulate_succ` で制御）に加えて PayPal。将来のゲートウェイを
  追加できるよう、`PaymentGateway` は enum のままにしている。
- トランザクションメールに **Resend**。`app.tasks.email.send_email` Celery タスクから送信する — `BackgroundTasks` では
  ないので、リクエストスコープ外の呼び出し元（同じく Celery タスクである `lottery_draw_service.draw_lottery`）からも
  メールを送れる。各メールの件名／本文は呼び出し箇所に直接書かず、`app/utils/email_templates.py` の `EmailTemplate`
  enum に置く。`settings.DEBUG=true` の場合、`.env.example` の `RESEND_API_KEY` がプレースホルダーであるため、メール本文
  （認証／リセットトークンを含む）は送信されずコンソールに出力される — 本番では必ず `false` にすること。
- お問い合わせページの FAQ 即時回答に **anthropic** SDK（`app/services/shared/faq_answer_service.py`、モデルは
  `claude-haiku-4-5`、`messages.parse` による構造化出力）。`app/content/faq.md` / `faq.ja.md` の内容だけから回答する。
  `ANTHROPIC_API_KEY` が未設定なら無効で、`DEBUG=true` の場合は API を呼ばずに出力する。
- S3 互換の画像ストレージに **boto3**（`STORAGE_BACKEND=s3` のときだけインポートされる）— §3 を参照。
- ローカル開発に Docker Compose（`app` + `postgres:16` + `redis`）。Dockerfile は `uvicorn` の前に
  `alembic upgrade head` を実行する。`PYTHONDONTWRITEBYTECODE=1` は、Docker Desktop for Windows のバインドマウントで
  古いバイトコードが残る問題を回避するため。
- pytest + pytest-cov + fakeredis（`tests/conftest.py` がテストセッション全体で偽の Redis クライアントに差し替える）+
  GitHub Actions → Codecov → Render へのデプロイ。

## 2. レイヤードアーキテクチャ

すべての機能は、4 つのドメインサブパッケージ（`identity/`、`talent/`、`events/`、`marketplace/`）と、ドメインを
横断する機能（通知、お問い合わせフォーム、FAQ 即時回答）のための `shared/` サブパッケージのいずれかの中で、同じ
3 層構造に従う。`cart`/`order`/`payment`/`shipping` は `marketplace/` 配下にある。`events` のチケット購入が
`payment_service` に依存しているのは、意図的にその境界をまたいでいるもの。

1. **`app/router/<domain>/<feature>.py`** — ルート関数のみ。`get_db`、`get_current_user`、`rate_limit(...)` を依存性
   として受け取り、サービスのメソッドを 1 つ呼び、その結果を HTTP レスポンスまたは `HTTPException` に変換する。
   ORM クエリもビジネスロジックも置かない。
2. **`app/services/<domain>/<feature>_service.py`** — 1 つの機能のすべての関数を、1 つのクラスの `@staticmethod` として
   持つ（`class TicketService: @staticmethod def checkout_ticket(db, ...): ...`）。呼び出しは
   `TicketService.checkout_ticket(db, ...)`。クラスは名前空間であり、インスタンス化はしない — `db` は呼び出しごとに
   渡す。プライベートなヘルパーも同じクラスの `@staticmethod` とし、`ClassName._helper(...)` で呼ぶ。モジュール
   レベルの定数はクラスの外に置く。ビジネスロジックと ORM クエリはここに置き、ルーターには決して置かない。
3. **`app/db/models/<domain>/<feature>.py`** — SQLAlchemy モデル。すべて `Base` を継承する。
   `app/schema/<domain>/<feature>.py` には対になる Pydantic スキーマ（`*Create`、`*Read`/`*Out`/`*Response`、
   `*Update`）を置く — レスポンスの形は常に ORM モデルとは別のクラスであり、ORM モデルを直接返すことはない。

   汎用的な確認応答（`{"msg": "..."}`）には `app/schema/common.py::MessageResponse` を
   `response_model=MessageResponse` で使う。これは本当にドメイン横断のものなので、`app/exception/common.py` と
   同じくどのドメインにも属さない場所に置いている。ページ単位のレスポンスを返すサービス関数（`concert_service`、
   `idol_service`、`group_service`、`product_service`、`ticket_service`、`cart_service`、`order_service`、
   `cache_service` にまたがる）は、素の `dict` ではなく実際のレスポンススキーマのインスタンスを組み立てて返す。
   `product_service._build_product_cards` は `list[ProductCard]` を返すので、呼び出し側は dict のキーではなく属性
   （`card.artist`）で読む。`ProductWithCategoryRead` は完全な `CategoryRead` オブジェクトを埋め込んでおり、
   `ProductRead` とは別のスキーマである。`ProductRead` の `category` フィールドは、`CacheService.get_cached_products`
   が組み立てる解決済みの名前（`str`）。`cache_service.py` も上の 2 番と同じ「`@staticmethod` の 1 クラス」の形
   （`class CacheService: ...`、`CacheService.get_cached_products(db)` として呼ぶ）に従い、関数を並べただけの
   モジュールではない。インポートを一方向に保つため、キャッシュは 2 つに分かれている:
   - `app/cache/invalidation.py`（`CacheInvalidation`）はすべてのキャッシュキーと `delete_cached_*` メソッドを持ち、
     Redis にのみ依存する。自身のトランザクションの流れの中で無効化しなければならないサービス（購入、決済の確定、
     抽選）はこちらをインポートする。
   - `app/cache/cache_service.py`（`CacheService(CacheInvalidation)`）はリードスルーの `get_cached_*` メソッドを持ち、
     キャッシュを埋めるためにサービスを呼ぶ。これをインポートするのはルーターだけで、ルーターは更新系のサービス
     呼び出しの直後に、継承した `delete_cached_*` も呼ぶ。

   サービスは決して `cache_service` をインポートしてはならない。循環が再発してしまうため。

サービス間の呼び出しもクラスを経由する（`PaymentService.create_ticket_payment(...)`、素の関数としては呼ばない）。
別々のサービスファイルにある同名の関数（例: `direct_sale_campaign_service.add_campaign` と
`lottery_campaign_service.add_campaign`）は無関係であり、共存して問題ない。サービス間呼び出しに対する
`unittest.mock.patch()` には、完全修飾の `"app.services.<domain>.<file>.<ClassName>.<method>"` パスが必要。

`app/db/base.py` はすべてのモデルを直接インポートして集約し、Alembic の `Base.metadata` がすべてを認識できるように
している — モデルファイルを移動したら、このインポートリストを手動で同期すること。

### エラー処理: センチネルではなく例外

サービスは、チェックが失敗したその場所で、具体的な失敗内容を示すメッセージとともに `NotFoundError`（404）、
`ForbiddenError`（403）、`BadRequestError`（400）— いずれも `app/exception/common.py` の `ServiceError` のサブクラス —
を送出する。ルーターは呼び出しを一度だけラップする:

```python
try:
    return XService.method(...)
except ServiceError as e:
    raise HTTPException(status_code=e.status_code, detail=str(e)) from e
```

- エラーだと判断する前に、呼び出し元がその結果を *調べて上書きする* 必要があるプライベートなヘルパー
  （例: `idol_service._validate_refs`）は、直接送出せずにセンチネルを返すままにする。
- 「見つからない」ときに `False`/`None` を返し、ルーター側でインラインに処理する単純な読み取り
  （`if not result: raise HTTPException(404, ...)`）は、この規約の影響を受けない。
  - 素のリストを返す読み取り（`db.query(X).all()`、それ以上の変換なし）は、結果が空かどうかを自分でチェックしない —
    `return db.query(X).all()` をそのまま返し、型は `list[X] | None` ではなく `-> list[X]:` とする。`.all()` は
    `None` ではなく常に `[]` を返し、ルーターの `if not result:` にとって `[]` は `None` と同じく偽なので、
    ラップし直しても、リストをそのまま返すのと違う動きをすることのない分岐が増えるだけ。同じ簡略化は、
    `db.get(...)`/`.first()` を *そのまま* 返すだけの単一オブジェクトの読み取りにも当てはまる — `return db.get(X, id)`
    をそのまま返し、型はその呼び出し自体が本当に `None` を返しうるので `X | None` のままにする。ただし、検索した
    1 行を中心に組み立てる詳細オブジェクト（`IdolDetailRead(idol=...)`）には **当てはまらない**: Pydantic モデルの
    インスタンスは常に真なので、`if not entity: return None` のガードだけが、ルーターが「見つからない」を判別する
    唯一の手段になる。コレクションから組み立てるページやリストのオブジェクト（`EventsPageRead`、`CartDetailRead`、
    ...）にはそのようなガードはない: 空であることも正当な結果である。
- **購入／決済の例外**（`app/exception/checkout.py`）: `CartItemError` とそのサブクラス（`InsufficientStockError`、
  `PaymentAmountMismatch`、`UnsupportedGatewayError` など）。サービスで送出し、ルーターで捕捉してステータスコードに
  マッピングする。新しい複数ステップのフローではこの形を使う。
- **DB トリガーのエラー**（`app/exception/db_triggers.py`）: `TriggerViolationError` + 名前付きの 10 個のサブクラス。
  12 個の Postgres トリガー（`database-design_JP.md` §7.5 に一覧）と、呼び出し元が区別する必要のある一意制約違反
  （冪等性キーの重複、券種の重複）をカバーする。トリガーが発火しうる書き込みでは、素の `db.commit()`/`db.flush()` の
  代わりに `commit_or_raise()` / `flush_or_raise()` を使う。各サブクラスは独自の `status_code` を持つ。1 つの関数が
  `TriggerViolationError` と `ServiceError` の両方を送出することもある（例: `ticket_service.checkout_ticket`）—
  ルーターは両方を捕捉する。

### レスポンス中のエラーコード

すべてのエラーボディは `{"detail": ..., "code": ...}` である（一覧は `api-spec_JP.md` §0）。`detail` は FastAPI の
通常の値。`code` は安定した snake_case の識別子で、フロントエンドは英語のテキストを解析する代わりにこれで分岐する。

- 上の 3 つの系統（`ServiceError`、`CartItemError`、`TriggerViolationError`）はすべて `CodedError`
  （`app/exception/common.py`）を継承しており、各クラスが `code` を持つ。送出箇所で、より具体的なケースのために
  上書きできる: `BadRequestError("...", code="entries_closed")`。ファン向けの新しいビジネスルールには独自のコードを
  与えること。マネージャー向けフォームの汎用的なチェックはクラスのコードのままでよい。
- ボディを組み立てるのは `app/exception/handlers.py`（`main.py` で登録）。コードは次の順で決まる: ルーターで送出
  された `ApiHTTPException`（例: `code="invalid_credentials"`）、`HTTPException` の送出 **元** になったエラー、
  ステータスごとのデフォルト（`not_found`、`not_authenticated`、`rate_limited`、...）。そのため、ルーターは上の
  `raise HTTPException(...) from e` パターンを守ること。**`from e` を落とすと、コードが黙ってステータスのデフォルトに
  格下げされる**。
- 空の結果はエラーではない: リストのエンドポイントは `[]` を、ページのエンドポイントは空のリストを持つオブジェクトを
  返す。`404` は特定のリソースが存在しない場合だけに使う。
- ルーター内で手動で検証するモデル（例: `Form(...)` フィールドから）は `request_validation_error(e)` を通じて
  再送出し、その 422 が FastAPI 自身のものと同じフィールドエラーのリストを持つようにする。
- **予期しない例外**: `UnhandledErrorMiddleware`（同じモジュール、`main.py` で `CORSMiddleware` より *前に* 追加し、
  CORS がそれを包むようにしている）がトレースバックをログに出し、`code: "internal_error"` 付きの JSON の 500 を返す。
  これがないと FastAPI はすべてのミドルウェアの外側で 500 を組み立ててしまい、レスポンスに CORS ヘッダーが付かず、
  ブラウザは 500 ではなくネットワークエラーとして報告する。
- 422 のリクエスト検証エラーは FastAPI のフィールドエラーのリスト形式の `detail` のままで、
  `code: "validation_error"` が付く。

### ルートハンドラー: `async def` ではなく `def`

ルーターより下のスタックはすべて同期的である: SQLAlchemy の `Session`、bcrypt、`httpx.post`（PayPal）、boto3。
FastAPI は `async def` のハンドラーをイベントループ上で直接実行するため、その中でブロッキングな呼び出しがあると、
プロセス内の他のすべてのリクエストが止まる。素の `def` のハンドラーはスレッドプールで実行される。そのため、
本当に何かを `await` するのでない限り、**ルートハンドラーは `def`** とする。

`async def` のハンドラーは 1 つもない。かつてそれを必要としていた 2 か所は、`run_in_threadpool` のラッパーを
使わずに対処した:
- **アップロード**: `storage.save()` は同期的で、`UploadFile.file` を読む。Starlette はハンドラーが実行される前に
  アップロード全体をスプールし終えているので、その読み込みはただのファイル I/O である。同期コードから
  `UploadFile.read()` を呼んではならない: これは非同期で、await されないコルーチンを返してしまう。
- **生のリクエストボディ**（`paypal_webhook`）: 唯一の `await request.body()` は小さな非同期の依存性（`_raw_body`）の
  中にある。FastAPI は非同期の依存性をループ上で await しつつ、`def` のハンドラーはスレッドプールで実行する。

新しいルートで `async def` が必要に思えたら、まず `await` をこのような依存性に移すこと。

これにより、1 つのプロセス内のリクエストが実際に並行して実行されるようになった。以前はすべてのハンドラーが
ループのスレッド上で最初から最後まで実行されていたため、プロセスごとに偶然直列化されていた。それを安全に保って
いるのが、購入と抽選における `FOR UPDATE` のロックである。

## 3. 横断的な要素

- **`app/deps/auth.py::get_current_user`** — Bearer JWT をデコードし、`Users` 行を読み込み、`request.state.user` を
  設定する（レートリミッターの `user_key` が読む）。`require_admin`/`require_manager_or_admin` は、非推奨の
  `is_admin` bool ではなく `current_user.role` をチェックする。
- **事務所スコープ**: テナントごとの Postgres スキーマではなく、共有スキーマ + `company_id` カラム + サービス層での
  フィルタリング。事務所が所有するリソースを管理するすべてのサービスは `_manager_scope_violation(current_user,
  company_id)` ヘルパーを持つ — マネージャーが自分の事務所の外で操作しようとしたときに `True` となり、
  `ForbiddenError` として送出される。読み取りはスコープしない。`products` は自身の `company_id` カラムを持たないので、
  `product_service._resolve_product_company_id()` を通じて間接的に `company_id` を解決する。`categories` には
  スコープがない — 更新系のエンドポイントはすべて `require_admin` 専用。
- **`app/cache/rate_limit.py::rate_limit(limit, window, key_func)`** — 依存性のファクトリ
  （`Depends(rate_limit(5, 60, ip_key))`）。キーにはルートのパスを含める（`_route_key`）ので、同じ `key_func` を
  共有するエンドポイント同士がカウンターを共有することはない。各リクエストは 1 つの `MULTI` トランザクションを
  実行する: `SET key 0 EX window NX`（そのウィンドウのカウンターが存在しない場合に限り、TTL 付きで作成）の後に
  `INCR`。両方が 1 つの単位として実行されるので、並行リクエスト間でチェックしてから実行するまでの競合はなく、
  クラッシュによって有効期限のないカウンターが残る（そのクライアントが永久にレート制限される）こともない。
  どちらのコマンドも他方の結果に依存しないのでトランザクションで十分であり、途中で読んだ値によって分岐する必要が
  あるロジックなら代わりに Lua スクリプトが必要になる。上限を超えた場合は `TTL` を読む（別の呼び出しで、429 の
  メッセージのためだけ）。Redis のエラー時には警告を出力してリクエストを通す（フェイルオープン）。3 つ目のキー関数
  `user_or_ip_key` は、認証が任意のルート（`get_current_user_optional`）向け: トークンが送られていればユーザーを
  キーにし、ゲストの場合は `ip_key` のバケットにフォールバックする。`user_key`/`user_or_ip_key` は
  `request.state.user` を読むので、シグネチャ内で認証の依存性を `rate_limit` より前に置かなければならない。
  Render のリバースプロキシの背後では、`main.py` がアプリを
  `uvicorn.middleware.proxy_headers.ProxyHeadersMiddleware` で包み、`ip_key` がプロキシの IP ではなくクライアントの
  IP を見るようにしている — ただし `trusted_hosts="*"` の場合、その IP は `X-Forwarded-For` の一番左のホップであり、
  これはクライアントが制御できる（`docs/bugs_JP.md` #7。修正計画は `docs/plans/rate-limit-client-ip_JP.md`）。

  **カバレッジのポリシー**:

  | ティア | キー | 典型的な上限 | 理由 | 例 |
  |---|---|---|---|---|
  | 認証／総当たり対策 | `ip_key` | 3–10 / 60s | クレデンシャルスタッフィングへの耐性 | `register`、`login`、`forgot_password` |
  | お金／在庫 | `user_key` | 3 / 60s | 希少な在庫やお金を確保する | `checkout_order`、`checkout_new_ticket`、`apply_to_lottery`、`add_to_cart` |
  | 権限昇格 | `user_key` | 3 / 60s | 高い権限を付与する | `make_admin`、`create_manager` |
  | 認証済みの読み取り | `user_key` | 10–60 / 60s | 軽いが、上限を設ける価値はある。ポーリングや起動時の読み取りは範囲の上限 | `notifications/unread-count`（60）、`me`（60）、`payment/status*`（20） |
  | 公開の読み取り | `ip_key` / `user_or_ip_key` | 10–30 / 60s | スクレイピング対策／DB コストの抑制 | `products/all`、`products/store-page`、`*/detail`（30）、`products/search`（10） |
  | お問い合わせフォーム | `user_or_ip_key` | 3–5 / 600s | 送信で任意のアドレスにメールが送れる。即時回答は有料の API 呼び出しになる | `inquiries/submit`（3）、`inquiries/instant-answer`（5） |
  | マネージャー／管理者の CRUD | `user_key` | 20–30 / 60s | リトライループへの安全網であり、セキュリティ対策ではない | ほとんどの `talent`/`events`/`marketplace` の管理系ルーター |

- **画像ストレージ（`app/utils/storage.py`）** — ABC（`StorageBackend`）と
  `LocalStorageBackend`/`S3StorageBackend` があり、`get_storage()` を通じて `settings.STORAGE_BACKEND` で選択される。
  アップロードを行うすべての箇所は、バックエンドを直接使わず `get_storage()` を経由する。
- ドメインの例外（§2）は、それを送出するルーターで一元的に捕捉する。

## 4. ローカルでの実行

```bash
cp .env.example .env   # fill in real secrets
docker compose up --build
# API docs: http://localhost:8000/docs
```

`docker compose up` は `worker` サービス（`celery -A app.celery_app worker`）も起動する。新しいテーブル／カラムは
必ず Alembic のマイグレーションを通し、`Base.metadata.create_all()` は決して使わない。enum 型は、クラッシュループに
対して安全ではない `Enum.create(bind, checkfirst=True)` ではなく、アトミックで冪等な `DO $$ BEGIN CREATE TYPE ...
EXCEPTION WHEN duplicate_object THEN NULL; END $$;` ブロックを使う。`GENERATED ALWAYS AS ... STORED` のカラムは
Postgres の enum にキャストできない（キャスト関数が `IMMUTABLE` ではなく `STABLE` のため）— 代わりに `VARCHAR` を
使う（`venues.size` を参照）。

テスト: `pytest --cov=app`。`tests/unit/`（モック使用、DB なし）と `tests/integration/`（実際の `TestClient`、Postgres
が必要）に分かれている。`tests/conftest.py` は結合テストの実行前に `DATABASE_URL` を専用の `<name>_test` データベースに
向け直すので、開発データに触れることはない。CI は Postgres 16 + Redis を立ち上げ、マイグレーションを実行し、
カバレッジ付きで pytest を実行し、Codecov にアップロードし、`main` では Render にデプロイする。

## 5. 新しいコードの規約

- ルートのプレフィックスは、既存のすべてのルーターに合わせて小文字にする（`/cart`、`/categories`、`/order`、
  `/payment`、...）。
- 更新系／ユーザースコープのクエリはすべて、`get_current_user` だけでなくクエリのレベルで `user_id` または
  `company_id` によるフィルタをかける。
- ORM オブジェクトを包む Pydantic スキーマには `model_config = {"from_attributes": True}` を設定する。
- 更新の判断をする前に `with_for_update()` で行をロックする。ロックと書き込みは同じトランザクション内に置き、
  その間に別の `db.commit()` を挟まないこと。
- **すべてのモデルファイルは `Base` を `app.db.base` ではなく `app.db.base_class` からインポートする。**
  `app/db/base.py` は `base_class` の `Base` を再エクスポートするだけの純粋な集約モジュールであり、モデルから
  `app.db.base` 経由でインポートし直すと循環インポートのバグが再発する（`app/deps/auth.py` と
  `app/router/marketplace/products.py` はどちらも `app.db.models.identity.user` を直接インポートしている）。
- 新しいモデルモジュールは `app/db/base.py` のインポートリストに追加しなければならない。そうしないと、SQLAlchemy が
  文字列ベースの `relationship()` 参照を解決する際に、スタンドアロンのスクリプトで
  `InvalidRequestError: ... failed to locate a name` が発生しうる。
- ETL パイプラインが構築されたら（`project_status_JP.md` §5）、それにデータを送る書き込みは同じトランザクション内で
  `domain_events` のアウトボックス行を発行すべきである。そのテーブルはまだ存在しない — 単一の機能のためにその場限りで
  作らないこと。
- 検証: CI はすべての push／PR で、Postgres 16 + Redis に対して `alembic upgrade head` とテストスイート全体
  （ユニット + 結合）を実行する。Postgres に接続できない状態で変更を行う場合は、`py_compile` による一括チェックと
  AST ベースの静的チェック（すべての `ForeignKey`/`relationship(back_populates=...)` のペアが解決でき、相互に対応して
  いること。アプリ内のすべてのインポートが解決できること）にフォールバックし、そのことを明記する — これは CI の代用で
  あって、置き換えではない。
- **すべての関数に戻り値の型を、すべての引数に型を付ける** — ruff の `ANN` ルールで強制している。`tests/*` と
  `scripts/*` は対象外。
  - 古いセンチネルを返す規約（`Literal["forbidden", "not_found"]`）は、ルーターが `_raise_for`/`_raise_for_link` を
    使っていた箇所では §2 の例外階層に置き換えられた — それらの関数は今は成功時の型だけを返す。単純な読み取りの
    「空の結果」のセンチネルは `Literal[False]` ではなく `None`（`Object | None`）とする — `None` は Python における
    本来の「何もない」を表す値であり、`db.get(...)`/`.first()` が見つからなかったときにすでに返す値なので、それらを
    ラップする読み取りが同じ意味の 2 つ目の偽の値を発明する必要はない。`idol_service._validate_refs` のような
    プライベートな複数値のセンチネルヘルパーは、依然として送出せずにセンチネルを返す（この次の項目を参照）— ただし
    センチネル自体は素の `Literal["a", "b", ...]` ではなく、ヘルパーの隣に置いたローカルな `class _RefIssue(str,
    Enum)` とする。理由は次の項目でモデルのカラムについて述べるのと同じで、メンバー名のタイプミスが、どの
    `if error == "...":` の分岐にも黙って一致しない文字列ではなく、呼び出し箇所での `NameError`/`AttributeError` に
    なるからである。`Literal` は本当にその場限りのインラインの型ヒントには今でも適切だが、複数の場所で比較される
    値の集合には適さない。
  - **固定された文字列値の集合（ロール、ステータス、販売方式、ティア、通知の種類、...）は、そのフィールドの
    Read/Update モデルをすでに持っているスキーマファイル内の `class X(str, Enum)` とし、許される値をコメントで
    書いただけの素の `str` にはしない。** モデルの `Column` も同じクラスを使う —
    `Column(Enum(OrderStatus, name="order_status_enum"))` とし、Python 側の型を一切持たないモジュールレベルの
    `Enum("a", "b", "c", name=...)` にはしない。`server_default=` は Python のデフォルト値ではなく DDL のテキストなので、
    素の文字列ラベルのままにする。これにより、不正な値は、コミットの奥深くで生の `IntegrityError` として表面化する
    `CHECK`／enum 違反ではなく、API の境界での Pydantic の検証エラーになる。`role`/`TicketType.tier`/
    `TicketType.sale_method`/`Concert.status`/`LotteryCampaign.status`/`DirectSaleCampaign.status`/
    `LotteryEntry.status`/`Ticket.status`/`Notification.type`/`Notification.status`/`AlbumDetail.format` はすべて
    現在これに従っている。2 つ上の項目の例外階層のセンチネル文字列（`Literal["forbidden", "not_found"]` など、今は
    返り値ではなく送出される例外）には当てはまらない — それらはモデルのカラムの値の集合だったことはない。
    `_validate_refs` のようなプライベートな複数分岐のセンチネル *ヘルパー* は中間的なケースで、モデルのカラムでは
    ないが複数の場所で比較されるので、1 つ上の項目のとおり、`Literal` ではなく enum の扱い（`_RefIssue`）にする。
  - **FastAPI の落とし穴**: デコレーターに `response_model=` がない場合、ルート自身の戻り値の型注釈が暗黙の
    レスポンススキーマになる。そこに素の SQLAlchemy ORM クラスがあると、インポート時にアプリがクラッシュする。
    ルートに `response_model=` がなく、実際の戻り値の型が Pydantic でシリアライズできない場合は、明示的に
    `response_model=None` を設定すること。
