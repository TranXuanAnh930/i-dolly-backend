# デプロイ — Render（API）+ Supabase（Postgres）+ Render Key Value（Redis）

[English](deployment.md) | 日本語

このリポジトリをローカルの Docker Compose から本番環境へデプロイする方法です: API は Render、データベースは
Supabase、キャッシュ／レートリミッターは Render 自身の Redis 互換アドオン、画像アップロードは S3 互換のオブジェクト
ストレージに置きます。マイグレーションのチェーン全体は、すべての push で CI（Postgres 16）上で空の状態から実行されて
おり、稼働中の Supabase データベースにもすでに適用済みです（`project_status_JP.md` §1/§3）。そのため、新規デプロイでの
`alembic upgrade head` の挙動はわかっています — それでも、新しいデータベースに対する初回起動時には注視してください。
§8 のロールバックに関する注意を参照してください。

## 0. 必要なアカウント

- [Render](https://render.com) — API と（下記のストレージ／Redis の選択に従えば）キャッシュをホストする。
- [Supabase](https://supabase.com) — Postgres をホストする。
- アイドル／商品画像のアップロード用の S3 互換オブジェクトストレージのアカウント — AWS S3、Cloudflare R2、
  DigitalOcean Spaces のいずれもそのまま使える（`app/utils/storage.py` は環境変数だけで 3 つすべてに対応しており、
  コードの変更は不要）。特にこだわりがなければ、無料枠が最も大きいのは Cloudflare R2。
- デプロイに本物の Resend アカウントは **必須ではない** — `app/config/settings.py` は `RESEND_API_KEY`/`FROM_EMAIL` が
  *設定されている* ことを要求する（そうでなければ Pydantic が起動を拒否する）が、実際にメール送信のコードパスを
  通らない限り、それらが有効である必要はない。ポートフォリオのデプロイならプレースホルダーの値で十分 — §7 の表を
  参照。モック決済ゲートウェイは設定不要。PayPal の経路には PayPal Sandbox アプリの認証情報（§7 の `PAYPAL_*` の行）が
  必要 — それがなければモックゲートウェイだけが動作する。

## 1. このデプロイに必要だったコード変更（対応済み）

このリポジトリには、ローカル開発を前提にハードコードされていて、実際のデプロイを黙って壊してしまう箇所が 2 つ
あった — このドキュメントの時点でどちらも修正済み:

- **CORS**（`main.py`）— ハードコードされた `["http://localhost:8080"]` だった。現在は `CORS_ORIGINS` 環境変数
  （カンマ区切りのオリジン）を読み、デフォルトは同じ値なのでローカル開発には影響しない。Render ではこれを実際の
  フロントエンドのオリジンに設定する（§7）。
- **メール認証のリンク**（`app/services/identity/auth_service.py`）— このプロジェクトの改名前の、特定の古い Render
  ドメインにハードコードされていた。現在は `BASE_URL` を読む（§7）。

それ以外にデプロイのためのコード変更は不要 — `Dockerfile` は起動時にすでに `alembic upgrade head` を実行してから
`uvicorn main:app --host 0.0.0.0 --port $PORT` を実行し、`$PORT` はまさに Render がすべての Web サービスに自動で
注入する環境変数である。

## 2. Supabase — Postgres

1. 新しい Supabase プロジェクトを作成する（Render のサービスをデプロイする場所に近いリージョンを選ぶ — リージョンを
   またぐ DB の往復は、すべてのリクエストに実際のレイテンシーを加える）。
2. **Settings → Database → Connection string。** Supabase はいくつかの種類を提示する — 直接接続ではなく、
   **Session pooler** の接続文字列（Supabase の現在の名称によってポート `6543` または `5432`）を使う。理由は 2 つ:
   - Supabase の直接接続は、IPv4 アドオンを購入しない限り、新しいプロジェクトでは IPv6 のみになる。Render の
     送信ネットワークは IPv6 をルーティングしない可能性があり、その失敗の仕方（接続がただハングする／タイムアウト
     する）は手探りでデバッグするには紛らわしい。プーラーは IPv4 で到達できる。
   - このアプリはサーバーレス関数ではなく、独自の SQLAlchemy コネクションプール（`app/db/session.py` の
     `create_engine(..., pool_pre_ping=True)`、デフォルトのプールサイズ）を持つ長寿命のサーバープロセスである —
     そのため Supabase に選択を求められたら、**Transaction mode** より **Session mode** のプーリングを選ぶ:
     トランザクションモードの pgbouncer は、SQLAlchemy が依存しうるセッションレベルの機能（例: プリペアド
     ステートメント）をサポートしないが、セッションモードはサポートする。
3. その接続文字列をコピーする — それが `DATABASE_URL`（§7）になる。すでに `sslmode=require` が含まれているので、
   削除しないこと。
4. 手動で SQL を実行する必要は **ない** — 初回起動時に Dockerfile の `alembic upgrade head` が、
   `alembic/versions/` のマイグレーション（執筆時点で 64 個、一本の直線的なチェーン）から、すべてのテーブル、
   トリガー、enum 型を作成する。

## 3. オブジェクトストレージ（S3 互換）— 永続的な画像アップロードのため

ローカルディスクのストレージ（`STORAGE_BACKEND=local`）は Render の再デプロイで消える — ファイルシステムは
一時的なものである。ここでは永続性を選択したので:

1. 選んだプロバイダー（S3 / R2 / Spaces）でバケットを作成する。
2. `idols/` と `products/` のプレフィックスを公開読み取りにする（または CDN を前段に置いて `S3_PUBLIC_URL_BASE` を
   設定する — 下記参照）— 現在のローカルディスクの経路と同じく、アップロードされた画像はブラウザから認証なしで
   取得できる必要がある。
3. そのバケットだけにスコープされたアクセスキーを作成する（アカウント全体のキーではなく）。
4. Render で次の環境変数を設定する（§7）: `STORAGE_BACKEND=s3`、`S3_BUCKET_NAME`、`S3_REGION`、
   `AWS_ACCESS_KEY_ID`、`AWS_SECRET_ACCESS_KEY`、そして R2/Spaces の場合のみ（本物の AWS S3 なら不要）プロバイダーの
   S3 互換エンドポイントを指す `S3_ENDPOINT_URL`。コードの変更は不要。`app/utils/storage.py` はすでに
   `STORAGE_BACKEND` で分岐している。

## 4. Redis — Render の Key Value アドオン

1. Render のダッシュボードで、§6 で作成する Web サービスと **同じリージョン** に新しい **Key Value**（Render の
   Redis 互換サービスの現在の名称）インスタンスを作成する — ここで同じリージョンであることが重要なのは
   レイテンシーのためだけではない: それによって無料の *内部* 接続が使えるようになる。
2. 外部接続ではなく、**Internal Connection** の情報（同じリージョンの他の Render サービスからのみ到達できる
   プライベートなホスト名 + ポート）を使う。Render の内部ネットワークでは TLS もパスワードも不要であり、これが
   重要なのは **`app/cache/redis_client.py` が現在 `host`/`port`/`db` でしか接続せず、パスワードにも TLS にも対応して
   いない** からである。Redis を Render の外（Upstash など）に移したり、外部接続文字列が必要になったりした場合は、
   小さなコードの追加（`redis.Redis(...)` 呼び出しへの `password=`、`ssl=True`）が必要になるが、まだ実装されていない。
3. `REDIS_HOST` に内部ホスト名を、`REDIS_PORT` にそのポート（通常は `6379`）を、`REDIS_DB` に `0` を設定する。

## 5. Render — Celery ワーカー

ワーカーは 2 つのタスクモジュールを実行する — マネージャーが実行する抽選（`app.tasks.lottery.draw_lottery`、
`docs/project_status_JP.md` §8）と、すべてのトランザクションメールの送信（`app.tasks.email.send_email`）— なので、
デプロイに必須の要素である。Celery Beat／スケジューラーは使っていない: すべての通知の発行元
（`docs/project_status_JP.md` §2）は cron ではなく、それを引き起こしたリクエスト／タスクの中でインラインに発火する —
そのため、デプロイが必要なのはワーカーだけで、2 つ目のスケジューラープロセスは不要。

1. **New → Background Worker**（Web Service ではなく）、同じリポジトリ、同じ `Dockerfile`。
2. **Start Command**: `/start-worker.sh`（イメージのデフォルトの `CMD`、つまり Web サービスの `/start.sh` を上書きする）。
3. 内部の Redis 接続のため、§4 の Key Value インスタンスと同じリージョンにする。
4. 環境変数: ワーカーは Web サービスと同じ `Settings` クラスを読み込むので、使うものだけでなく §7 の **必須の変数
   すべて**（データベース、Redis、3 つの `JWT_*` シークレット、3 つの `*_EXPIRE_*` の値、
   `RESEND_API_KEY`/`FROM_EMAIL`）が必要で、そうでなければ起動しない。すべてのトランザクションメールを送信するので、
   `RESEND_API_KEY`/`FROM_EMAIL`/`DEBUG` は Web サービスと一致させなければならない。`CELERY_BROKER_DB` のデフォルトは
   `1` で、別のインデックスを使いたい場合以外は設定不要。ここにマイグレーションのステップはない。Web サービスの
   起動時に、同じデータベースに対してすでに `alembic upgrade head` が実行される。

## 6. Render — Web サービス

1. **New → Web Service** で、`TranXuanAnh930/i-dolly-backend` の GitHub リポジトリを接続する。
2. **Runtime: Docker。** Render はリポジトリの `Dockerfile` から直接ビルドする — ビルド／起動のコマンドは不要で、
   Dockerfile 自身の `CMD ["/start.sh"]` が `alembic upgrade head` と `uvicorn` の起動の両方を担う。
3. リージョン: §4 の Key Value インスタンスと同じ（内部の Redis 接続が機能するため）で、Supabase のリージョンに
   できるだけ近いところ。
4. インスタンスタイプ: ポートフォリオのデモなら無料枠で動くが、Render の無料 Web サービスは非アクティブな状態が
   続くとスピンダウンし、コールドスタートが遅いことに注意 — 履歴書のリンクとしては問題ないが、誰かが初回読み込みの
   レイテンシーを計測するなら、そのことを伝えること。
5. §7 の表にあるすべての環境変数を追加してから、サービスを作成する。初回デプロイではイメージのビルド、
   マイグレーションの実行、アプリの起動が行われる — 特にマイグレーションのステップについてデプロイログを注視する
   こと（§8）。

## 7. 環境変数 — 完全なチェックリスト

| 変数 | 値 | 備考 |
|---|---|---|
| `DATABASE_URL` | Supabase の session pooler の接続文字列（§2） | |
| `DATABASE_NAME` / `DATABASE_USER` / `DATABASE_PWD` | 空でない任意の値。例: Supabase の接続文字列からコピー | `app/config/settings.py` のスキーマで必須だが、**`app/` 内のどこからも実際には読まれていない** — 元の docker-compose 専用の構成の名残。アプリが起動するように設定しておく。これだけのためにコードを変更する価値はない。 |
| `JWT_SECRET_KEY` / `JWT_REFRESH_SECRET_KEY` / `JWT_EMAIL_SECRET_KEY` | 互いに異なる 3 つのランダムなシークレット | `python -c "import secrets; print(secrets.token_hex(32))"` でそれぞれ 1 回ずつ生成する |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | `15` | `.env.example` と一致 |
| `REFRESH_TOKEN_EXPIRE_DAYS` | `7` | |
| `EMAIL_TOKEN_EXPIRE_MINUTES` | `60` | |
| `REDIS_HOST` / `REDIS_PORT` / `REDIS_DB` | §4 から | 内部ホスト名、通常は `6379`、`0` |
| `CELERY_BROKER_DB` | `1`（デフォルト、省略可） | Celery ワーカー（§5）もデプロイする場合にのみ関係する |
| `RESEND_API_KEY` / `FROM_EMAIL` | 本物のキー、またはプレースホルダー | お問い合わせの確認メールを含む、すべてのトランザクションメールを送信する |
| `ANTHROPIC_API_KEY` | Claude API のキー、または **省略** | お問い合わせページの AI 回答（`POST /inquiries/instant-answer`）を有効にする。省略した場合、エンドポイントは常に「回答不可」を返し、フロントエンドはフォームだけを表示する。 |
| `DEBUG` | **省略、または `false`** | 開発専用: プレースホルダーの `RESEND_API_KEY` では実際に配信できないとき、認証／リセットトークンをコンソールに出力する（`architecture_JP.md` の Resend に関する注記）。未設定の場合のデフォルトは `false` で、ここではそれが望ましい — これらのトークンの本文が Render の共有ログに出る理由はない。 |
| `BASE_URL` | `https://<your-render-service>.onrender.com` | メール認証のリンクを組み立てるのに使う |
| `FRONTEND_BASE_URL` | フロントエンドの実際のオリジン | PayPal の `return_url`/`cancel_url` を組み立てる。デフォルトは `http://localhost:8080` |
| `PAYPAL_CLIENT_ID` / `PAYPAL_CLIENT_SECRET` | PayPal Sandbox（または本番）アプリから | 省略するとモックゲートウェイだけで動作する |
| `PAYPAL_MODE` | `sandbox`（または `live`） | |
| `PAYPAL_WEBHOOK_ID` | PayPal のダッシュボードにある Webhook の ID | `POST /payment/paypal/webhook` の署名検証に使う |
| `CORS_ORIGINS` | フロントエンドの実際のオリジン（カンマ区切り） | 例: `https://your-frontend.vercel.app` |
| `STORAGE_BACKEND` | `s3` | §3 で選択したとおり |
| `S3_BUCKET_NAME` / `S3_REGION` / `AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY` | §3 から | |
| `S3_ENDPOINT_URL` | プロバイダーのエンドポイント | **本物の AWS S3 では省略**、R2/Spaces では必須 |
| `S3_PUBLIC_URL_BASE` | 任意の CDN／カスタムドメイン | 未設定の場合は、計算で求めたバケットの URL にフォールバックする |

## 8. 初回デプロイ — 本当のリスクはマイグレーション

Dockerfile が出力する `Running Alembic migrations...` の行について、Render のデプロイログを注視する。チェーン
（UUID 主キーへの書き換えと 12 個のトリガーすべてを含む）は CI で空の状態からクリーンに実行でき、Supabase にも
適用済みだが、新しいデータベースや新しいマイグレーションでは、ここで失敗する可能性がまだある。途中で失敗した場合:

- Render のログに、どのリビジョンが失敗したかと、Postgres の生のエラーが表示される。
- 前に進める形で修正する: マイグレーションファイルを直してコミットし、Render に再デプロイさせる — Supabase の
  スキーマを直接手で編集しないこと。そうするとマイグレーションの履歴と稼働中のスキーマが乖離する。
- マイグレーションが失敗する前に部分的に適用されていた場合（例: `CREATE TABLE` は成功したが、同じファイル内の後続の
  `CREATE TRIGGER` が失敗した）、再試行の前に Supabase の SQL エディタで、そのマイグレーションが作成したものを手動で
  削除する必要があるかもしれない — Alembic は、失敗したマイグレーション自身の DDL を Postgres のトランザクショナル
  DDL の範囲で自動ロールバックするわけではなく、1 つの `upgrade()` 内の複数の `op.execute()` 呼び出しも自動的に
  1 つのアトミックな単位になるわけではない。この問題は実際に起きたときに対処すればよく、推測で先回りして解決しない
  こと。

## 9. CI/CD の自動デプロイの接続（任意、下地は用意済み）

`.github/workflows/test.yml` にはすでに `deploy` ジョブがあり、テストが通った後、`main` へのすべての push で
`RENDER_DEPLOY_HOOK` シークレットに `curl` する — これはフォーク元の Render サービス向けに設定されていたものなので、
このリポジトリ用にシークレットを追加し直す必要がある:

1. 新しい Render サービスの **Settings → Deploy Hook** で、デプロイフックの URL をコピーする。
2. `TranXuanAnh930/i-dolly-backend` の GitHub リポジトリの **Settings → Secrets and variables → Actions** で、
   その URL を `RENDER_DEPLOY_HOOK` として追加する。ワークフローの他のシークレット（`JWT_SECRET_KEY` など）は、実際の
   デプロイではなく CI の Postgres/Redis サービスに対する *test* ジョブでのみ使われる — Render の環境変数と一致させる
   必要はない。

## 10. デプロイ後のスモークテスト

1. `https://<your-service>.onrender.com/docs` — Swagger UI が表示されるはず。
2. `POST /account/register` → `POST /account/login` — DB 接続と JWT のフローを確認する。
3. `GET /products/all` — Redis（商品一覧のキャッシュ）に到達できることを確認する。
4. データを投入する場合: `render shell` でサービスに入る（または Render の単発ジョブで）、`python scripts/seed.py`
   （日本語版なら `python scripts/seed_ja.py`）を実行する — 冪等なので、新しい Supabase の DB に対して一度実行しても
   安全。

## 11. このデプロイに持ち越される既知の制限事項

- Celery ワーカー（§5）は必須: マネージャーが実行する抽選を処理し、すべてのトランザクションメールを送信する。
  ワーカーがないと `PUT /concerts/lottery-draw/{id}` は "scheduled" を返すが抽選は実行されず、メールも一切配信
  されない。
- `app/cache/redis_client.py` はパスワード／TLS に対応していない（§4）ので、Redis は Render の内部ネットワーク経由で
  到達できる必要がある。
- IP ベースのレート制限は `X-Forwarded-For` の一番左のホップを信頼しており、Render のプロキシの背後ではクライアントが
  これを偽装できる（`docs/bugs_JP.md` #7、修正計画は `docs/plans/rate-limit-client-ip_JP.md`）。
- Redis の障害により、キャッシュされた読み取りとコミット後のキャッシュ無効化が 500 になる（`docs/bugs_JP.md` #11、
  修正計画は `docs/plans/redis-outage_JP.md`）。
- PayPal の Webhook の経路は実際の配信を一度も受け取ったことがなく、決済拒否の経路も実際に拒否された決済で試されて
  いない（`docs/project_status_JP.md` §7）。
- Render の無料枠は非アクティブ後にコールドスタートする。デモでそれが問題になるなら、遅い初回読み込みがバグに
  見えてしまう前に、そのことを伝えること。
