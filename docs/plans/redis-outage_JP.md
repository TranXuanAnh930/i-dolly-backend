# 修正計画: Redis の障害を乗り切る（bugs_JP.md #11）

[English](redis-outage.md) | 日本語

**ステータス:** 計画済み、未着手（2026-09-27）。

## 問題

Redis は 3 つの役割を担っている。障害に対処しているのはそのうち 1 つだけ:

| 役割 | コード | `RedisError` のとき |
|---|---|---|
| レート制限 | `app/cache/rate_limit.py` | 捕捉され、リクエストは許可される（フェイルオープン） |
| キャッシュされた読み取り | `CacheService.get_cached_*`（`app/cache/cache_service.py`） | 捕捉されない → 500 |
| 書き込み後の無効化 | `CacheInvalidation.delete_*`（`app/cache/invalidation.py`） | 捕捉されない → 500、**DB のコミットの後で** |
| Celery ブローカー（メール、抽選） | ルーター／サービス内の `celery_app.send_task(...)` | 捕捉されない → 500、これもコミットの後 |

1. **Postgres なら応答できるのに読み取りが失敗する。** DB へのフォールバックが実行される前に `redis_client.get()` が
   送出するので、ストア、イベント、詳細、マネージャーのページがすべて 500 になる。キャッシュの障害がサイトの障害に
   なってしまう。
2. **成功した書き込みが失敗として報告される。** 例: `OrderService.checkout`: `commit_or_raise(db)` が注文、決済、
   在庫の変更を保存し、その後 `CacheInvalidation.delete_cached_products()` が送出する。ファンは支払い済みの注文に
   対して 500 を受け取り、確認メールも届かず（ルーターの `send_task` が実行されない）、新しい冪等性キーで再度購入して
   しまうかもしれない → 注文の重複。決済の確定、チケット購入、抽選（#25）、マネージャーのあらゆる作成／更新／削除でも
   同じ形になる。
3. **失敗ではなくハングする。** `app/cache/redis_client.py` は `socket_timeout` / `socket_connect_timeout` を設定して
   いない。接続が拒否された場合はすぐに失敗するが、黙って切断された場合は OS が諦めるまでブロックする。止まった
   リクエストはそれぞれスレッドプールのスレッドと DB 接続（プールは 5 + 5）を保持するので、数件で API 全体が止まり
   うる。

## 決定事項

- **読み取りはフェイルオープンにする**: `RedisError` のときは Postgres からレスポンスを組み立て、キャッシュへの
  書き込みは省略する。
- **無効化の失敗はログに出して握りつぶす。** コミットは取り消せないので、レスポンスはそれを反映しなければならない。
  代償: Redis が復旧した後に古いキャッシュエントリが残るが、その期間は `TTL_SECONDS`（5 分）で制限される。
  ポートフォリオプロジェクトとしては許容し、`architecture.md` に記載する。（Render Key Value が
  `persistenceMode: off` で行うように Redis が空の状態で再起動した場合は、古いものは何も残らない。）
- **短いクライアントのタイムアウト**: `socket_connect_timeout=1`、`socket_timeout=1`（秒）。Redis の呼び出しは通常
  5 ms 未満で済む。1 秒は通常よりはるかに長く、それでいてスレッドをすぐに解放できる。
- **コミット後の `send_task` はベストエフォート**: ログに出して続行する。メールは失われるが、これは既存の「メールの
  失敗は握りつぶされる」というスメルと同じである。本当の修正はアウトボックス（OLAP の今後の取り組みを参照）。
  `PUT /concerts/lottery-draw/{id}` には **当てはまらない**。ここではキューに入れること *自体が* 操作なので、
  マネージャーが再試行できるよう、引き続き明示的に失敗（503）させるべきである。
- ルーターごとの try/except ではなく、キャッシュ層に 1 つのガードを置く。

## 手順

1. `app/cache/redis_client.py` に **タイムアウト**: `socket_connect_timeout` と `socket_timeout` を追加する（設定
   `REDIS_SOCKET_TIMEOUT: float = 1.0`）。`health_check_interval=30` も検討する。
2. `app/cache/invalidation.py` に **無効化のガード**: `redis.RedisError` を捕捉し、メソッド名とともに
   `"cache invalidation skipped: ..."` をログに出し、`None` を返す小さなデコレーター（またはコンテキストマネージャー）、
   例えば `@_best_effort`。すべての `delete_*` と `_delete_matching` に適用する。
3. `app/cache/cache_service.py` に **読み取りのガード**: 各 `get_cached_*` の `get` と `setex` を包む。`get` が失敗
   → キャッシュミスとして扱う。`setex` が失敗 → それでもペイロードを返す。最もシンプルな形: `RedisError` を握り
   つぶす 2 つのヘルパー `_cache_get(key) -> bytes | None` と `_cache_set(key, value)` を用意し、すべての
   `get_cached_*` が `redis_client` を直接使う代わりにそれらを呼ぶ。
4. **コミット後のメール送信**: `celery_app.send_task("app.tasks.email.send_email", ...)` を `try/except
   kombu.exceptions.OperationalError`（+ `redis.RedisError`）で包み、ログに出して続行するヘルパー（例:
   `app/utils/email_dispatch.py::dispatch_email`）。メールのための直接の `send_task` 呼び出しをこれに置き換える。
   抽選をキューに入れる処理はそのままにするが、その失敗を 503 にマッピングする。パブリッシュのリトライポリシーも
   確認すること: Celery はデフォルトでパブリッシュをリトライするので、数秒の遅延が加わりうる —
   `broker_transport_options`/`task_publish_retry_policy` を設定して、すぐに諦めるようにする。
5. **ロギング**: `print` ではなく `logging.getLogger(__name__)` を使う（`app/` での `logging` の初めての本格的な使用。
   レートリミッターの `print` も同時に移行できる）。
6. **テスト**
   - ユニット: `redis_client.get`/`setex`/`delete` が `redis.ConnectionError` を送出するようにパッチし、各
     `get_cached_*` が DB のデータを返し、各 `delete_*` が送出せずに戻ることをアサートする。
   - ユニット: 無効化が送出する状態での `OrderService.checkout` → 注文を返す（例外なし）。
   - ユニット: `send_task` が送出する状態での `dispatch_email` → 例外なし。
   - 結合（任意）: 2 つ目のクライアントを未使用のポートに向け、キャッシュされたページ + 購入を叩く。200 と正しい
     データを期待する。
   - ネガティブコントロール: 各テストが現在のコードに対して失敗すること。
7. **ドキュメント**: `architecture.md`（キャッシュのセクション: フェイルオープンの読み取り、ベストエフォートの無効化、
   タイムアウト、古さの上限）、`project_status.md` §4、`bugs.md` の #11 にチェックを付ける。

## 関連

- **#25**（抽選が失敗として報告される）: Redis の停止はその発生要因の 1 つ — コミット後の
  `delete_cached_concert_detail` が抽選の中で送出する。手順 2 でその発生要因はなくなるが、#25 には独自の修正がある
  （コミット後のステップを抽選の失敗経路から分離する）。
- **#22** の残り半分と **#7** も `rate_limit.py` に触れるが、この計画とは衝突しない。
