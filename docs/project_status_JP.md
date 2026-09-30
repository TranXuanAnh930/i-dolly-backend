# プロジェクトの状況

[English](project_status.md) | 日本語

何が作られ、何が検証済みで、何がまだ未解決かのスナップショットです — 何かが存在する、あるいは完成していると判断する
前にこれを読んでください。`database-design_JP.md`（同じフォルダ）はスキーマ／ビジネスロジックの設計、
`architecture_JP.md` はコードの構成を扱います。このファイルは「今どこにいるか」の層であり、最も古くなりやすいもの
です — 機能が実際に入ったり既知の問題が修正されたりしたら、そのたびに更新し、願望の状態に流れていかないようにして
ください。

## 1. 現在のマイグレーションの状態

**チェーンのヘッド: `b8e2d4f6a1c3`**（`create_inquiries_table`）— 64 個のマイグレーション、一本の直線的なチェーンで、
分岐はない。CI はすべての push／PR で、Postgres 16 に対して空の状態から `alembic upgrade head` を実行し、その後
テストスイート全体を実行する。`b8e2d4f6a1c3` までのチェーンは `develop` 上でそこを通過した（2026-09-29、CI の実行
131）。Supabase にはまだ再適用していない。`a3f7c9e2b6d4`（`add_password_reset_to_notification_type`）までは、本物の
Postgres インスタンスに対して適用・確認済み: `alembic upgrade head` は空の状態からクリーンに実行でき、
`alembic current` はヘッドのリビジョンを報告し、`notifications` のテーブル／enum はモデルと一致した。通知の機能は
実際の HTTP でもエンドツーエンドで試され（パスワードリセット → 通知の作成 → 読み取り → 未読数がクリアされる）、
ルートごとのレートリミッターが負荷の下で発動することも確認した（30/60s の予算は 30 回目を超えたリクエストに `429`
を返す）。アプリは今では本物の Supabase の Postgres に対してもデプロイされており（§3）、そこでは現在のヘッドまで
マイグレーションがクリーンに実行される。`54347349d0f2` と `bfadb696c92a`（項目 5 のスキーマの型の修正）は、これまで
静的にしか検証していない（`py_compile`、`alembic` 自身のリビジョンチェーンのチェック）。まだ Supabase に対して再実行
していない。`c7f2a4d8e1b5` と `d3a9e5f1c8b7` は、使い捨ての Postgres データベース（このドキュメント全体で使っている
シード／検証のパターン）に対して再実行 *した*: 空の状態からの `alembic upgrade head` は毎回クリーンに完了し、
`enum_range(NULL::notification_type_enum)` で `lottery_draw_triggered`/`lottery_draw_failed` が存在することを確認した —
これらが追加した 3 つの新しい発行元については、下の §2 の「通知」の項目を参照。特に `d3a9e5f1c8b7` の発行元は、enum
だけでなくそれ以上まで試した: 同じデータベースに対して、抽選キャンペーンがまだ締め切られていない公演で
`draw_lottery_task` を直接呼び、`BadRequestError` が伝播し、`lottery_draw_failed` の行が入ることを 1 回の実行で確認した。
`7c7c3f5e19fc`（`add_lottery_draw_completed_to_notification_type`）、`e4f8b2a6c9d1`
（`drop_album_details_cover_image_url`）、`f1a7c3e9b5d2`（`add_order_shipped_to_notification_type`、今回のセッションの
発送ステータスの作業、項目 43）、`a9d3f5b7c1e2`（`unique_shipping_status_order_id` — 一意制約を追加、項目 43）は、
これまで静的にしか検証していない（`py_compile`、`alembic` 自身のリビジョンチェーンのチェック）— 当時は Docker
Desktop のエンジンに接続できなかった。**その後、実際に実行した（2026-09-25）:** 結合テストスイートの空の状態からの
`alembic upgrade head` で、4 つすべてがクリーンに適用された（235/235 のテストが成功）。

`database-design_JP.md` の 18 のドメインテーブルと、既存の EC のテーブルはすべてマイグレーション済み。
`database-design_JP.md` 全体で「参照用の DDL」として引用されている `schema.sql` は、このリポジトリにファイルとしては
存在しない — すべてのマイグレーションは DDL ファイルから書き写したのではなく、設計ドキュメントに対して直接書いた。
必要になったら、稼働中のマイグレーション／モデルから生成すること。

列挙への耐性のため、すべての主キー／外部キーは連番の整数ではなく UUID である。これはすべてのモデル、
マイグレーション、スキーマ、ルーター／サービスの ID パラメータ、JWT の `sub` クレームの扱い、そして商品一覧の Redis
キャッシュに影響する（msgpack にはネイティブの UUID 型がないので、`msgpack.packb` の前に `p.id` を文字列化する）。

`lightstick_details` → `merch_details` の改名（`b60aec9ffc02`）は、`ALTER TABLE ... RENAME TO` が制約の名前に触れない
ため、Postgres が自動で名前を付けた 5 つの制約（主キーと 4 つの外部キーすべて。元のマイグレーションで明示的に名前を
付けていなかった）を最初は取りこぼしていた — `133d9b4f9d17` が残りを改名する。`database-design_JP.md` §3.17 を参照。

## 2. 作られているもの

- **Identity／RBAC**: `users.role`/`company_id`、`management_companies`、`require_admin`/`require_manager_or_admin`
  （`app/deps/auth.py`）、事務所が所有するすべてのリソースのサービスにある事務所スコープのヘルパー。`UserOut` は
  `role`/`company_id` を返す。管理者は `POST /profile/create-manager` で、事務所に紐づく `role="manager"` の
  アカウントを直接作成できる。
- **Talent**: `groups`、`idols`、`idol_colors`、`positions`/`idol_positions` — 完全な ORM + スキーマ + サービス +
  ルーター、事務所スコープの CRUD。
- **Events & ticketing**: `venues`、`concerts`/`concert_performers`、`ticket_types`、`lottery_preferences`、
  `lottery_campaigns`、`lottery_entries`、`direct_sale_campaigns`、`tickets` — 完全な ORM + スキーマ + サービス +
  ルーター。チケットは 3 つの方法で作成される: 抽選（§8）、一般販売の購入（`POST /tickets/checkout`、§5）、そして
  管理者専用の手動発行（`POST /tickets/add`、サポート／テストのために残している暫定措置）。
- **Marketplace**: `categories.is_resale_capped`、`album_details`、`genres`/`album_genres`、`merch_details` — 完全な
  ORM + スキーマ + サービス + ルーター。
- **画像のアップロード**: `idols.profile_image_url` / `products.image_url`、ローカル／S3 のストレージの抽象化
  （`app/utils/storage.py`）、作成時のインラインのアップロードと、後で置き換えるための専用の
  `POST /{domain}/{id}/image`。詳細: `database-design_JP.md` §9。
- **シードデータ**（`scripts/seed.py`）: 冪等 — 事務所 3 社、ユーザー 8 人、5 グループ + ソロ 3 人にわたるアイドル
  25 人、会場 6、公演 6、券種 18（抽選 + 一般販売）、カテゴリ 5、20 品目のマーケットプレイス、希望／応募付きの抽選
  キャンペーン 2 件、手動発行のチケット 1 枚。アイドルの肖像と商品のジャケットは、本物の `get_storage().save()` の
  パイプラインを通した手続き的なプレースホルダーのアート — `tests/fixtures/README.md` を参照。`scripts/seed_ja.py` は
  同じ構造の日本語版の代替（`seed.py` のヘルパーを再利用する。カラー／ポジション／ジャンル／カテゴリのような
  ルックアップのキーとフィクスチャのファイル名は英語のまま）。この 2 つはデータベースごとに排他的で — どちらかの
  目印となる事務所が存在すれば、それぞれスキップする。
- **通知**（`app/db/models/shared/notification.py`）: 12 種類のイベントをカバーし、参照するエンティティの種類ごとに
  nullable な FK を 1 つずつ持つ `notifications` テーブル（`database-design_JP.md` §3.19）。発行元はインラインで発火
  する（cron／Beat のジョブはない）: `order_service.checkout()`、`ticket_service.checkout_ticket()`/
  `checkout_won_ticket()`、`user_service.verify_rtoken()`、`lottery_draw_service.draw_lottery()`（すべての当選者と
  落選者に `lottery_result`、加えて当選者には支払いのリマインダー。期限が近づいてから予定どおりにではなく、抽選時に
  発火する。自身のコミットが入った直後に、`lottery_draw_completed` のために
  `concert_service.notify_managers_of_draw_completion()` も呼ぶ — 実行した人だけでなく、公演の事務所のすべての
  マネージャーに）、`lottery_entry_service._stage_entry()`（`lottery_registered`。ファンの応募がステージされた瞬間に
  発火する — 単一と一括の応募エンドポイントで共通で、応募自体と同じコミット）、
  `concert_service.notify_managers_of_draw_trigger()`（`lottery_draw_triggered`。マネージャー／管理者が抽選を押した
  瞬間に `PUT /concerts/lottery-draw/{id}` のルーターから発火する — クリックした人だけでなく、公演の事務所のすべての
  マネージャーが受け取る。抽選自体は Celery ワーカーに投げっぱなしで、これが、抽選が進行中であることを彼らの誰もが
  得られる唯一の記録だからである）、`concert_service.notify_managers_of_draw_failure()`（`lottery_draw_failed`。
  `app/tasks/lottery.py` の `draw_lottery_task` 自身の `except Exception` ブロックから呼ばれる — ロールバックし、
  トリガーの通知と同じ対象に通知し、その後元の例外を再送出するので、タスクは黙って成功したように見えるのではなく、
  Celery の `FAILURE` として表に出る。§8 の更新された通知の注記を参照）、そして `order_service.ship_order()`
  （`order_shipped`。マネージャー向けの「発送」ボタンである `PATCH /order/{order_id}/ship`（§4 の項目 43）から、
  注文の購入者本人に、`"shipped"` へのステータスの切り替えと同じコミットで発火する）。すべての書き込みは、それが
  説明するイベントと同じコミットに入る。ファン向けの API: `GET /notifications/mine`、`GET /notifications/unread-count`
  （ポーリング型、WebSocket／SSE のレイヤーはない）、`POST /notifications/{id}/read`、`POST /notifications/read-all` —
  自己スコープ、レート制限あり。`event_reminder` にはまだ発行元がない。`notifications.status`/`sent_at` はいずれに
  しても永久に `pending`/`null` のまま — その組は、このテーブル自体が駆動しない受信箱へのプッシュのステップを追跡
  するものである（下のメール送信を参照。別の経路）。
- **お問い合わせ（contact form、お問い合わせ）**: `POST /inquiries/submit`。ゲストにも開かれている（ログイン中の
  送信者は `user_id` で紐づけられる）。すべてのお問い合わせは `inquiries` テーブル（`database-design_JP.md` §3.20）に
  保存され、他のすべてのメールと同じ Celery の `send_email` タスクを通じて、入力されたアドレスに確認メールが送られる。
  メールは入力されたどんなアドレスにも届くので、悪用対策として 2 つの選択をした: 確認メールにはユーザー自身の
  テキストを決して含めない（トピックのラベルと参照 ID だけ）ので、このフォームを使ってこちらのアドレスから任意の
  内容を送ることはできない。そして 1 つのアドレスが受け取る確認メールは 1 時間に最大 3 通
  （`InquiryService.CONFIRMATIONS_PER_ADDRESS`）で、ルート自体もユーザーまたは IP ごとに 10 分あたり 3 件の送信に制限
  されている。アドレスごとの上限を超えた場合でも、お問い合わせは保存され、メールだけが省かれる。既知の隙間: 同じ
  アドレスへの 2 件の同時送信が両方とも上限のチェックを通過しうる（お金に関わるものではないので許容）。`+tag` の
  エイリアスは別のアドレスとして数えられる。そして **スタッフ向けの閲覧の経路はまだない** — お問い合わせは
  データベースの中でしか見られず、届いても誰にも通知されない。8 件のユニットテストとユニットテストスイート全体
  （475/475）、そしてルートが登録されることを確認する `import main` で検証した。マイグレーションとスイートは、その後
  CI で Postgres に対して通過した（§1）。まだ実際に Resend を通して送ったことはなく、ルートの結合テストもない。
- **お問い合わせページの FAQ の即時回答 — 実装済み、まだ本物の API に対して実行していない**。モデル:
  `claude-haiku-4-5`。最も安い選択肢で、`effort` の設定はなく（Haiku 4.5 はそれを拒否する）、プロンプトキャッシュも
  使わない（Haiku 4.5 は 4,096 トークン以上のプロンプトしかキャッシュせず、トラフィックの少ないサイトでは
  キャッシュの書き込みのほうが節約分より高くつく）。`DEBUG=true` の場合、サービスは `send_email()` と同じく、質問を
  出力するだけで Claude を呼ばない。途中で切れた（`max_tokens`）回答や拒否された回答は「回答不可」を返す。ユニット
  テストは自分で `DEBUG` を設定し、呼び出し経路が実行される箇所ではすべて `_client` を偽物にするので、`.env` の内容に
  かかわらず、どのテストも実際のリクエストを送ることはできない。語り口は開発者が決めた: 明るくかわいらしく、事実は
  正確に述べる（§5 の商品のパーソナリティを参照）。`POST /inquiries/instant-answer`（認証は任意、ユーザーまたは IP
  ごとに 10 分あたり 5 回）は `FaqAnswerService.answer` を実行する。これは `app/content/faq.md` の内容だけから回答し、
  役に立てないときは常に `{"answerable": false}` を返す: FAQ がそれをカバーしていない、`ANTHROPIC_API_KEY` が未設定、
  モデルが断った、または呼び出しが失敗した。お問い合わせフォームが常にフォールバックなので、エラーにはならない。
  Claude の呼び出し（`faq_answer_service._ask_claude`）は、FAQ をシステムプロンプトに入れ、`messages.parse` で
  `FaqAnswer` への構造化出力を得る。`requirements.txt` に `anthropic==1.8.0` を追加した（ドライランのインストールで
  衝突はなかった）。FAQ にはコードで確認された事実だけを載せている。返金、チケットの譲渡、会場への入場、送料、
  支払い方法のポリシーはまだどこでも決まっていないので、ファイルのヘッダーのコメントに TODO として挙げている。
  検証: 9 件のユニットテスト（ユニットテストスイート 484/484）と、キーを設定しない状態でのプロセス内の HTTP 呼び出しが
  `200 {"answerable": false}` を返すこと。**日本語対応**: 日本語の FAQ（`app/content/faq.ja.md`）が `faq.md` を項目
  ごとに対応させており、即時回答のリクエストの新しい `lang` フィールド（`"en"`/`"ja"`、デフォルト `"en"`）で選ばれる。
  2 つのファイルは手で同期させなければならない。完結した日本語の質問は 10 文字より短いことがある（「返金できますか？」
  は 8 文字）ので、両方のお問い合わせのエンドポイントでメッセージの最小の長さを 10 から 5 文字に下げた。確認済み:
  全角スペースは通常のスペースと同じように取り除かれ、全角のメールアドレスの文字は拒否され（フロントエンドは NFKC で
  正規化する）、サーバーは長さを Unicode のコードポイントで数える。**まだ英語のみ**: 確認メール
  （`EmailTemplate.INQUIRY_RECEIVED`、およびその他すべてのトランザクションメール）と、`422`/`429` のエラーの
  テキスト。フロントエンドはそれらを表示する代わりに、エラーを独自の日本語のメッセージにマッピングする。この変更後の
  ユニットテストスイートは 489/489。
- **メール送信**: すべてのトランザクションメール — 認証のリンク、パスワードリセット、注文の受付、チケットの確定、
  抽選チケットの支払いの確定、お問い合わせの受付 — は `celery_app.send_task("app.tasks.email.send_email", ...)` を
  通り、`app/tasks/email.py` のワーカータスクに拾われ、それが `app/utils/email_sender.py` の Resend のラッパーを呼ぶ。
  各メールの件名／本文は、それぞれの呼び出し箇所に直接書くのではなく、`app/utils/email_templates.py` の
  `EmailTemplate` enum（`.subject`、`.render(**fields)`）に置いている。元の `BackgroundTasks.add_task` のやり方
  （認証メールのみ）を置き換えるもの — それは Celery タスク自身のワーカープロセスからは動かなかった（送信をぶら
  下げるためのリクエストスコープの `BackgroundTasks` がない）。これは `draw_lottery` がまだ自分で当落のメールを送って
  いたときに問題になった。今はもう送っていない（下記参照）が、アプリの残りは元に戻すのではなく、一貫性のために
  Celery ベースの送信を保った。これは上のアプリ内の `notifications` テーブルとは独立している: どちらも同じきっかけの
  イベントで発火するが、一方がもう一方にデータを送ることはない。**`draw_lottery` は意図的にメールを一切送らない** —
  当落はアプリ内の `lottery_result` 通知だけ（§8）。シードのファンの実際のメールアドレスに対して抽選のフローを
  テストしても、抽選のたびに本物の受信箱に大量のメールが届かないようにするためのスコープ変更である。もう何も参照
  しないので、`LOTTERY_WON`/`LOTTERY_LOST` は `EmailTemplate` から削除した。
- **Celery ワーカー**（`app/celery_app.py`、`app/tasks/`）: ブローカー + リザルトバックエンドは同じ Redis
  インスタンス上で、キャッシュ／レートリミッターとは別の DB インデックス。2 つのタスクモジュール:
  `app.tasks.lottery.draw_lottery`（マネージャーが実行、§8）と `app.tasks.email.send_email`（上のすべてのメール送信）。
  このフェーズでは Celery Beat／スケジューラーは使っておらず、計画もない — すべての発行元はインラインで発火する。
  定期的なジョブ（支払い期限のリマインダー、ETL の定期処理）は未解決のまま — §5 を参照。
- **12 個の DB トリガー／8 個のトリガー関数** が、`database-design_JP.md` §4 に挙げたお金／公平性の不変条件を強制
  している（ファンのみ購入可能、転売防止の上限、公演のチケットキャパシティ、抽選の応募上限、希望の必須チェック、
  抽選の希望と公演の一致、アルバム／グッズの相互排他のペア）。
- **機械可読なエラーコード**（2026-09-29）: すべてのエラーボディは `{"detail", "code"}`。例外は `code`
  （`CodedError`）を持ち、`app/exception/handlers.py` がそれをレスポンスに加え、空の結果は `404` ではなく `200`（`[]`
  または空のページオブジェクト）を返す。予期しない例外は CORS ヘッダーを保った JSON の 500（`internal_error`）を返し
  （`UnhandledErrorMiddleware`）、手動で検証したフォームのモデルは FastAPI 自身のものと同じ 422 のフィールドエラーの
  リストを返す。一覧: `api-spec_JP.md` §0。仕組み: `architecture_JP.md` §2。追加的な変更なので、`detail` だけを読む
  既存のクライアントは影響を受けない。

## 3. 検証方法（とその限界）

~~このプロジェクトのほとんどは、稼働中の Postgres／ネットワーク接続に到達できない状態で作られてきた~~ —
**完了**: アプリは Supabase を Postgres のバックエンドとして Render（API）にデプロイされている。
`alembic upgrade head` は本物の Supabase インスタンスに対してクリーンに実行でき、デプロイされたアプリは稼働していて
到達可能であり、実際のエンドポイントがエンドツーエンドで試されている — §7 の PayPal Sandbox での購入は、ローカルと、
この同じデプロイ済みの Render アプリの両方で確認した具体例の 1 つである。`pytest` のスイート自体は依然として、
デプロイ済みの Supabase のデータベースではなく、使い捨ての Postgres（`tests/integration/conftest.py`）に対して
ローカルで実行している — それは「デプロイ済みのアプリがエンドツーエンドで動く」とは別の作業であり、ここでは主張
していない。

日々のローカル開発は、ほとんどの変更について依然として稼働中の Postgres に到達できない状態で行っているので、
それらは次の方法で検証する:

1. `app/`、`main.py`、`alembic/` 全体に対する `py_compile` の一括チェック。
2. すべての ORM モデルの `ForeignKey` の参照先と `relationship(back_populates=...)` のペアを AST ベースでスキャンし、
   すべての FK とリレーションシップのペアが解決できることを確認する。
3. アプリ内のすべての `from app.X import Y` 文を AST ベースでスキャンし、インポートされた名前が参照先のモジュールに
   存在することを確認する。

どちらも実際の SQL や稼働中のアプリを試すものではない — ある変更がそこで別途試されていないものについては、上の
デプロイレベルの検証の代用であって、置き換えではない。ローカルで稼働中の Postgres／Redis に到達できたときは、検証は
さらに進んでいる: `pip install` + `import main` のエンドツーエンド、実際のインポートに対する（構文だけでない）
`pytest tests/unit`、そして特に通知の機能については、空の状態からの完全な `alembic upgrade head` に加えて、実際の
HTTP で機能を動かし（登録 → パスワードリセットを要求 → それを完了 → `/notifications/mine`、`/unread-count`、`/read`
で通知を確認）、負荷の下でレートリミッターを確認した（予算を超えると 429）。その実行: 339/339 のテストが成功し、
リグレッションはなかった。

**結合テストは以前、共有の開発用データベースに対して直接実行されていた** — `app`/`worker`/`scripts/seed.py` が使う
のと同じもの。いくつかのテストは、テーブルが 0 行で `404`／空を返すことをアサートしていたが、それは本当に空の
データベースに対してしか成り立たず、実際のシードデータがあると失敗していた。根本から修正した: `tests/conftest.py` は
今、他の何かが `app.config.settings` をインポートする前に、`DATABASE_URL` を専用の `<name>_test` データベースに向け
直し、`tests/integration/conftest.py` はテストセッションごとに一度、そのデータベースを削除・再作成・完全に
マイグレーションする。`pytest tests` は今や開発用 DB の状態にかかわらず決定的で、実際のデータに触れることはない。
`pytest tests/unit` は稼働中の Postgres をまったく必要としない — 向け直しは純粋な文字列の書き換えである。

**ユニットのカバレッジの取り組み（`pytest --cov=app`、46% → 大幅に上昇、213 → 393 のユニットテスト）**: ユニットの
カバレッジがゼロだったすべてのイベントドメインのサービス（`ticket_type_service`、`lottery_campaign_service`、
`direct_sale_campaign_service`、`lottery_entry_service`、`lottery_preference_service`、`concert_service`、
`venue_service`）を埋め、`test_cache_service.py` を追加し（`CacheService` がキャッシュ層のすべてであるにもかかわらず、
以前はテストがなかった — そのテストはテストごとのモックではなく `tests/conftest.py` のセッション全体の `fake_redis`
に対して実行されるので、キャッシュヒットは本当にラップされたサービスの呼び出しを飛ばし、削除は本当にキーを消す）、
`test_notification_service.py` を追加し、既存の `product_service`/`payment_service`/`shipping_service`/`user_service` の
テストファイルで欠けていた分岐（`get_product_detail` のおすすめのロジック、`finalize_paypal_payment` のチケット／
注文の分岐、`verify_rtoken` など）を埋めた。

**ここでは意図的にカバーしていないもの**: `ticket_service.checkout_ticket`/`checkout_won_ticket` と
`order_service.checkout` — 項目 1 の売り越しの競合の修正の背後にある、`with_for_update()` による悲観的ロックの経路。
これらは代わりに本物の Postgres に対して競合のテストをしている（§5 を参照）: `checkout` は
`test_orders_concurrency.py`、`checkout_ticket` は `test_ticket_checkout_concurrency.py`、`checkout_won_ticket` は
`test_won_ticket_checkout.py`。

**結合テストのカバレッジの取り組み 2（本物の Postgres 16 + Redis に対する `pytest --cov=app`、行カバレッジ 85.3% →
94.6%、745 → 923 のテスト、すべて成功）**: 最初の 2 回の取り組みがモックに任せたり飛ばしたりした RBAC／事務所
スコープとお金の経路を狙った。`tests/integration/_seed.py`（DB に直接入れるフィクスチャの行 + 任意のロールの JWT の
発行。一括の `DELETE` で後片付けし、Postgres の `ON DELETE CASCADE` が API の作成した行も削除する）、注文の発送処理
（キャンセル／発送／管理者の上書き、事務所スコープのマネージャーの注文ページ）、商品の管理（詳細付き作成の
スコープ、画像のアップロード、一括追加、マネージャーページ、販売履歴、アーティストの解決）、アイドル／グループの
書き込み、配送先住所の所有権、チケット／公演のルーターのエラーのマッピングについての HTTP レベルのスイート、3 つの
競合テストを含む `checkout_won_ticket` のサービスレベルのスイート、そして Celery タスク、`email_sender`、
`db_triggers`、両方のストレージバックエンドのユニットテストを追加した。その過程で実際のバグを見つけて修正し
（§4 の項目 47）、それが浮き彫りにしたマネージャーページの認証の穴を塞いだ（項目 48）。モジュールごとの数値、各
スイートが証明していること、残っている隙間: **`docs/test-coverage_JP.md`**。

## 4. 既知の問題／技術的負債（単独ではなく、周辺のコードとあわせて修正する）

アイドルチケットのドメインにとっての重要度のおおよその順に並べている。「修正済み」と記した項目は、フォーク元の
ボイラープレートにもともとあったバグで、このプロジェクトの間に解消したもの — 新たに持ち込んだものではない。

1. ~~**購入手続きが 1 つのアトミックなトランザクションになっておらず、在庫の売り越しの競合がある**~~ — **修正済み**。
   `order_service.checkout()` はカートの合計と転売上限をチェックし、必要なすべての `Product` の行にわたって 1 つの
   `ORDER BY Product.id ... with_for_update()` のロックを取り（UUID の順で、デッドロックに対して安全）、`Order`/
   `OrderItem` の挿入と `create_payment()`（コミットしない）の間それを保持し、`commit_or_raise()` で一度だけコミット
   する — `ticket_type`/`sold_quantity` についての `ticket_service.checkout_ticket()` の「ロックを保持して一度だけ
   コミットする」パターンと同じである。まだ未解決: 抽選ジョブ（§8）にも最初から同じガードを設計する必要がある。

   **見つけて修正したリグレッション**: 上のロックは本物だったが、転売上限のあるカテゴリの商品では黙って効いて
   いなかった（`categories.is_resale_capped` は DB レベルでデフォルトが `true()` — category.py:16 — なので、これは
   エッジケースではなく普通のケースだった）。数行前にある転売上限の事前チェック
   （`capped_products = db.query(Product).filter(...).all()`）が、本当の在庫チェックのクエリの `with_for_update()` が
   実行される *前に*、同じ `Product` の行をセッションのアイデンティティマップに読み込んでいた。Postgres は依然として
   正しく行ロックを取っていたが、SQLAlchemy は新しくロックした行ではなく、ロック前の古い Python オブジェクトを
   返していたので、`product.quantity < item.quantity` は古いデータに対して実行されていた。直接確認した: 上限のある
   カテゴリで `quantity=1` に対して 3 つの同時の購入手続きを競合させると、3 つすべてが「成功」し、最終的な在庫は
   `-2` ではなく `0` になった — 典型的な更新の消失で、各スレッドが同じ古い `quantity=1` を読み、それぞれ独立に `0` を
   書き込んでいた。`with_for_update()` のクエリに `.populate_existing()` を加えて修正した。これにより SQLAlchemy は、
   アイデンティティマップのコピーを新しくロックした行で上書きする。これは目視ではなく、下の新しい並行性のテストで
   見つけて確認した — ロックは書面上は正しく読めたので、表面化させるには、本物の Postgres に対する本当の並行
   トランザクションが必要だった。

   **検証**: `tests/integration/marketplace/test_orders_concurrency.py`（2 つのテスト: 在庫 1 個に対して 3 つの購入手続きを
   競合させる売り越しのガードと、N 個の在庫に対して N 個の購入手続きを競合させ、ロックが過度に直列化しないことも
   確認する在庫ちょうどのバリエーション）と `tests/integration/events/test_lottery_concurrency.py`（同じ公演に対して
   2 つの同時の `LotteryDrawService.draw_lottery` の呼び出しを競合させ、そこでの同じ `with_for_update()` のパターン —
   下の項目 8 — が実際に直列化することを確認する）。どちらも共有の `tests/integration/_concurrency.py` のハーネス
   （モックではなく、Docker で動かした本物のテスト用 Postgres に対して `threading.Barrier` で同期させた競合スレッド）
   を使う。修正後、スイート全体がクリーンであることを再確認した: ユニット 393/393、結合 235/235（既存の 232 + これら
   新しい 3 つ）。
2. ~~**レートリミッターのキーにルートが含まれていない**~~ — **修正済み**。`ip_key`/`user_key` は今、
   `request.scope["route"].path` を Redis のキー（`rate:ip:<route>:<ip>`）に含めるので、`key_func` を共有するエンド
   ポイント同士が 1 つのカウンターを共有することはもうない。
   ~~**`ip_key` に `X-Forwarded-For`/`X-Real-IP` の処理がなかった**~~ — **修正済み**。Render のリバースプロキシの背後
   では、`request.client.host` はすべての訪問者について Render 自身のエッジの IP だった。手作りの `X-Forwarded-For` の
   解析ではなく、`uvicorn.middleware.proxy_headers.ProxyHeadersMiddleware`（Render のネットワークだけがコンテナに
   直接到達できるので `trusted_hosts="*"`）でトランスポート層で修正した — そのヘッダーはクライアントが設定できる
   ので、素朴な解析では攻撃者がリクエストごとに新しいバケットを作れてしまう。
   ~~**さらに 2 つの本当のバグ**~~ — **修正済み**: (a) リミッターの `GET` → 条件付きの `SETEX`/`INCR` の流れは
   アトミックでない「チェックしてから実行」で、同時リクエストの集中がすべて「まだカウンターがない」と見て、決して
   制限に引っかからないことがありえた。1 つの `MULTI` トランザクション（`SET key 0 EX window NX` + `INCR`、下の注記を
   参照）に置き換えた。(b) Redis の呼び出しの周りにエラー処理がなかった — 障害時には、ログインを含むレート制限された
   すべてのルートが 500 になっていた。今は `try/except redis.RedisError` で包み、障害時には強制よりも可用性が重要
   なので、フェイルクローズではなくフェイルオープン（リクエストを通す）にしている。`tests/unit/test_rate_limit.py`
   （逐次的な制限のテストと、`limit=10` のバケットに 50 件のリクエストを投げるスレッドによる並行性のテスト）で
   カバーしている。`user_key` は依然として、`request.state.user` を設定するために `get_current_user` が先に実行される
   ことに暗黙的に依存している — 規約によって成り立っている、強制されていない順序であり、それ自体はバグではない。

   ~~**残るリスク: `INCR` と条件付きの `EXPIRE` が 2 つの別々の呼び出しだった**~~ — **修正済み**（`docs/bugs_JP.md`
   #22）。その間でのクラッシュ、再起動、接続の切断があると、TTL のないカウンターが残り、それは増え続けるだけなので、
   そのクライアントはそのルートで永久に 429 を受けていた。今は `SET key 0 EX window NX` と `INCR` が 1 つの
   `MULTI`/`EXEC` トランザクションに入る: キーは常に TTL 付きで作成され、2 つのコマンドの間に何も実行されることは
   ない。Lua スクリプトでも動くが、必要ない: 古い版で Lua が必要だったのは `INCR` の結果（`if count == 1`）で分岐して
   いたからにすぎず、`SET … NX` はその条件を Redis の中に移すので、固定のコマンドのリストで十分である。これにより、
   `EVAL` のための `fakeredis` の追加の `lupa` への依存も避けられる。ユニットテスト: `test_counter_always_has_a_ttl`
   （TTL が設定されていることをチェックする。クラッシュの時間の隙間自体はユニットテストでは再現できない）。
3. ~~`app/db/base.py` がすべてのモデルをインポートしていなかった~~ — **修正済み**。`Base` は今
   `app/db/base_class.py` にあり、`app/db/base.py` は純粋な集約モジュールである。`architecture_JP.md` §5 を参照。
4. ~~**Webhook の処理が冪等でない**~~ — PayPal を実際に統合した時点で **修正済み**（§7）。`finalize_paypal_payment` は
   `payment.status == pending` のときだけ実際の処理を行うので、重複した、または順序の乱れた Webhook の配信は、二重の
   処理ではなく何もしない操作になる — 別のイベント ID の台帳が必要なかった理由は §7 を参照。
5. ~~**スキーマの型の小さな不整合**: `Product.price` は `Float` なのに `OrderItem.price` は `Integer`（注文履歴で
   小数の価格が切り捨てられる）。`ShippingAddress.postal_code` は `Integer` で、英数字の郵便番号（英国、カナダ、
   日本）で壊れる~~ — **修正済み**。2 つのマイグレーション（`54347349d0f2`、`bfadb696c92a`）: `orders_items.price` →
   `Float`、`shipping_addresses.postal_code` → `String`。どちらも既存のカラムを広げるものなので、バックフィルは不要。
   HTTP の境界での `response_model=`／リクエストボディの型変換によって型の修正が黙って元に戻されないよう、対応する
   Pydantic のスキーマ（`OrderItem`、`ManagerOrderItemRead`、`ProductSaleRead`、`ShippingBase`）もあわせて更新した。
6. ~~**CORS の `allow_origins` がハードコードされている**~~ — **修正済み**。`main.py` は `CORS_ORIGINS` の設定（カンマ
   区切り、デフォルト `http://localhost:8080`）から `origins` を組み立てる — `docs/deployment_JP.md` を参照。
7. ~~**`cart_service.add_to_cart` が `Product` の行をロックしない**~~ — **修正済み**。在庫のチェックは今、隣の `Cart` の
   行の検索と同じく、`with_for_update()` でロックした行に対して実行される。購入手続き自身のロック（項目 1）がすでに
   お金の安全性の本当のゲートだった — `add_to_cart` は決して `product.quantity` を減らさない — が、このロックがないと、
   同時のカート追加が購入手続きの途中で減らす前の数量を読んでしまいうる。売り越しの問題ではなく、古いデータを読む
   問題である。
8. ~~**抽選ジョブに独自の並行性ガードが必要**~~ — **修正済み**。§8 を参照。
9. ~~**トリガーのエラーにきれいな着地点がない。**~~ — **修正済み**。`app/exception/db_triggers.py` は
   `TriggerViolationError` + 型付きの 8 つのサブクラス、捕捉した `DBAPIError` の Postgres のメッセージを各トリガーの
   既知の文言と照合する `translate_trigger_error()`、そしてトリガーが発火しうるあらゆる書き込みで素の
   `db.commit()`/`db.flush()` を置き換える `commit_or_raise()`/`flush_or_raise()` を追加する。トリガーでカバーされた
   挿入／更新に到達するサービス関数とそのルーターに組み込まれ、それぞれが `TriggerViolationError` を捕捉して
   `e.status_code`（ファンのみ購入可能のトリガーは 403、それ以外は 400）でマッピングする。
   `app/exception/checkout.py` と同じ「サービスで送出し、ルーターで捕捉する」形に従う — `architecture_JP.md` §2 を参照。
10. ~~`products`/`categories` にまだ事務所スコープがない~~ — **`products` については修正済み**。`categories` は、
    カテゴリを変更するすべてのエンドポイントがすでに `require_admin` 専用なので、そもそも必要なかった。商品には
    `company_id` のカラムがないので、`product_service._resolve_product_company_id()` は、それを参照している
    `album_details`/`merch_details` のいずれかを通じて、次にその行の `idol_id`/`group_id` を通じて所有者を解決する。
    `update_product`、`set_product_image`、`delete_product` は今これをチェックし、自分の事務所の外のマネージャーに
    対して `ForbiddenError` を送出する。どちらのテーブルにも紐づかない商品（素のグッズ）は所有者なしに解決され、
    どのマネージャーのものでもないままになる — 隙間ではなく意図的な状態である。素の `Product` は作成時にはまだ
    アイドル／グループとのつながりを持たないので、`add_product`/`add_bulk_products` はスコープされないままにする。
11. ~~**古くなったユニット／結合テストが本番のコードからずれていた**~~ — **修正済み**。`TestProductService`、
    `TestCategoryService`、`TestCartService`、`TestUserService`、`TestPaymentService` にまたがるいくつかのテストが、
    すでに正しいサービスのコードからずれていた — 項目 10 のスコープの修正で追加された必須パラメータ、間違った
    `*Update` クラスに入れ替わったスキーマ、新しい `with_for_update()` の段を考慮していないモックのチェーン、文書化
    された列挙対策の挙動（§4 の項目 18）と矛盾するアサーション、そして必須の `idempotency_key` フィールドの欠如
    （項目 16）。すべてアプリのバグではなくテストのバグだった — どの失敗も、入ったサービスの変更にスイートが追い
    ついていなかったもので、テストをそれに合わせて更新して修正した。
12. ~~**シードのアカウントが、ハードコードされ公開でコミットされたパスワードを共有している**~~ — **修正済み**。
    `scripts/seed.py` は管理者 1 人、マネージャー 3 人、ファン 12 人をすべて同じパスワードで作成する — 今は環境変数
    から読む `SEED_PASSWORD`（`os.environ.get("SEED_PASSWORD", ...)`）で、古いハードコードされた文字列はローカル開発
    用のフォールバックのデフォルトとしてだけ残している。`.env.example` はこの変数を記載している（任意で開発専用なので
    コメントアウトしている）。本物のデータベースに対してこのスクリプトを実行する前に実際にそれを設定するのは、依然
    としてデプロイする人の責任である — これが解決するのは「リポジトリにコミットされ、どこでも黙って同じ」という
    問題であって、「そもそも推測可能なアカウントで本番のデプロイにシードしない」という問題ではない。それは
    デプロイする人の別の判断である。
13. ~~**商品の書き込みで不正な `category_id` を渡すと生の 500 でクラッシュした**~~ — **修正済み**。
    `add_product`/`update_product`/`add_bulk_products` は存在チェックなしで `category_id` を設定していたので、不正な ID は
    4xx ではなく、コミット時に捕捉されない `IntegrityError` を送出していた。`update_product` は今 `NotFoundError` を送出
    する。`add_bulk_products` は参照されるすべてのカテゴリを最初にチェックし、全件成功か全件失敗かにする。
14. ~~**素の「Merch」の商品に事務所の所有者がまったくない**~~ — **修正済み**。マネージャーは、*名前* がどの事務所の
    ものかを示しているのに、それを強制する構造上のつながりがないグッズを編集／削除できた — `_resolve_product_
    company_id` にはグッズの所有者を解決する対象が何もなかった。ほぼ同じ 2 つ目の詳細テーブルを作るのではなく、
    `Lightstick` カテゴリを `Merch` に統合し、`lightstick_details` を `merch_details` に一般化することで修正した —
    ビジネスルールの中で、ペンライトとその他の公式グッズを実際に区別するものは何もなかった。理由の全体:
    `database-design_JP.md` §3.15/§3.17。
15. ~~**`shipping_addresses` の行を持つユーザーでは `DELETE /profile/delete` が 500 になった**~~ — **修正済み**。
    `Users` の `shipping_addresses`/`cart`/`orders`/`payment` へのリレーションシップに `passive_deletes` がなかったので、
    SQLAlchemy は親の削除の前に各子の `user_id` を null にしようとし — FK はすでに DB レベルで `ON DELETE CASCADE` を
    宣言しているのに、それが `NOT NULL` 制約に違反していた。4 つすべてに `passive_deletes=True` を加えて修正し、
    SQLAlchemy が Postgres 自身のカスケードに任せるようにした。
16. ~~**どちらの購入のエンドポイントにも、クライアントの再試行に対する冪等性がない**~~ — **修正済み**。
    `payment.idempotency_key` は `UUID NOT NULL UNIQUE` のカラムで、`PaymentCreate`/`TicketCheckoutCreate` はどちらも
    それを必須とし、購入手続きは他のことをする前に一致するキーをチェックして、2 つ目の `Payment` 行を作るのではなく
    `DuplicateIdempotencyKeyError` を送出する。ダブルクリックや再試行は今、二重課金ではなくきれいな拒否を受ける。
17. ~~**`delete_group`/`delete_idol` が行をハードデリートしていた**~~ — **修正済み**。どちらも実際のカスケードの挙動を
    持つ FK の参照先である — ハードデリートは公演の出演者の履歴を消したり（`ondelete="CASCADE"`）、商品のアーティストの
    帰属を宙に浮かせたり（`ondelete="SET NULL"`）してしまう。どちらのサービスも今は `is_active` による論理削除を行い、
    対応する `reactivate_group`/`reactivate_idol` のエンドポイントがある。ストア向けの読み取りは `is_active=True` に
    フィルタし、マネージャー／管理者の読み取りと ID による取得はフィルタしないので、編集フォームは無効化された行を
    読み込んで再有効化できる。グループを無効化してもそのアイドルには連鎖しない。無効化されたアイドル／グループは
    *新しい* 紐づけ（アイドルをそこに割り当てる、新しいリリースを紐づける）を受け付けないが、既存のものには触れない。
    どちらの `Update` スキーマも部分的なボディではないので、再有効化は一般的な `PUT /update` のフィールドではなく、
    専用の `PATCH .../activate/{id}` である。
18. ~~**認証／リセットのトークンを開発中に確認する手段がなかった**~~ — **修正済み**。ローカル開発では
    `SENDGRID_API_KEY` はプレースホルダーなので、認証／リセットのメールは常に送信に失敗し、送信はリクエスト／
    レスポンスのサイクルの外で行われる（元は `BackgroundTasks` の呼び出しで、今は Celery タスク — 項目 27）ので、
    中のトークンが目に見える形で着地する場所がなかった。`settings.DEBUG=true` は今、本物の SendGrid の呼び出しを
    試みる前に、トークンを含むメール本文全体をコンソールに出力する。API のレスポンスでトークンを返すことで解決
    しなかったのは意図的である: `forgot-password` は意図的に列挙対策をしており（メールアドレスが登録されているか
    どうかにかかわらず同じレスポンス）、レスポンスに本物のトークンがあると、そのサイドチャネルが再び開いてしまう。
    本番では `DEBUG` は必ず `false` にすること。

19. ~~**ファンが同じ公演について、一般販売のチケットと有効な抽選の権利の両方を持てた**~~ — **修正済み**。
    `lottery_entry_service.apply_to_lottery` は、ファンに別のティアの抽選への応募を許す前に、既存の有効なチケットを
    チェックしていなかった — 今は存在すれば `BadRequestError` を送出する。`ticket_service.checkout_ticket` は一般販売の
    購入の前に抽選の状況をチェックしていなかった — 今はその公演の抽選の応募がまだ `pending` または `won` なら
    `LotteryEntryUnresolvedError` を送出する。有効なチケットなしで `won` のケース（当選したのに支払い期限を過ぎさせた
    ファン）は、`trg_tickets_one_per_concert` だけでは捕まえられない隙間である。本物のフィクスチャの行に対する 4 つの
    新しい結合テストで検証した。
20. ~~**`pytest tests` が共有の開発用データベースに対して直接結合テストを実行していた**~~ — **修正済み**。修正の全体は
    §3 を参照。これが、本当に空のデータベースに対してしか成り立たない「空のテーブル」の挙動をアサートしていた十数件の
    テストの実際の根本原因だった — 十数件の別々のバグではなく、1 つの共通のバグ。
21. ~~**購入のたびに商品一覧のキャッシュが古くなる**~~ — **修正済み**。`order_service.checkout()` も
    `payment_service.finalize_paypal_payment()` も、どちらも `Product.quantity` を減らすのに、購入が成功しても商品の
    キャッシュを無効化していなかった。どちらも今、数量の書き込みを制御するのと同じ成功条件のもとで、コミットの直後に
    `delete_cached_products()` を呼ぶ。`get_cached_products` は依然として、スキーマを再利用するのではなく `ProductRead` の
    一部を生の dict として手で組み立てている — スキーマの変更はキャッシュの経路には伝わらない。ここでは対処して
    いない。同じ取り組みで `get_store_page_data` をキャッシュの対象に加え、2 つ目の手作りの dict ではなく、本物の
    `StorePageRead` モデルをダンプして組み立てた。`paginated_product`/`filter_product` はキャッシュしないまま —
    `filter_product` のキーの空間は無制限でクライアントが制御するので、キャッシュすると、めったに読み返されない
    書き込みのコストを払い、認証されていない呼び出し元に Redis をゴミのキーで埋める手段を与えることになる。
22. ~~**ほとんどの関数に戻り値の型がなく、約 3% の引数に型がなかった**~~ — **修正済み**。`app/router` と
    `app/services` にわたる 406 件の実際の指摘で、今後は ruff の `ANN` ルールで強制する — `tests/*`/`scripts/*` は対象外。
    センチネルを返す関数には、ゆるい `str` ではなく正確な `Literal["forbidden", "not_found"]` のユニオンを付けた。
    注釈を書く過程で 2 つの本当のバグ（余分な引数による `TypeError`、インスタンスが期待される箇所でのリストによる
    `ValidationError`）と、FastAPI の落とし穴を見つけた — デコレーターに `response_model` がない場合、ルート自身の
    戻り値の型注釈が暗黙の `response_model` になるので、そこに素の ORM クラスがあるとインポート時にアプリが
    クラッシュする。必要な箇所で `response_model=None` にして修正した。理由の全体: `docs/architecture_JP.md` §5。
23. ~~**2 つのエラー処理の規約が共存していた: RBAC／事務所スコープの失敗のほとんどには文字列のセンチネル、購入／
    決済と DB トリガーの違反には本物の例外**~~ — **修正済み、例外に統一**。古い `_raise_for`/`_raise_for_link` の
    センチネルのパターンを使っていた 14 組のルーター + サービスはすべて、今は `NotFoundError`/`ForbiddenError`/
    `BadRequestError`（`app/exception/common.py`）を送出する — `docs/architecture_JP.md` §2 を参照。古いパターンが
    すべての失敗理由を 1 つの包括的な文字列で済ませていたのに対し、各送出箇所にはより具体的なメッセージを付けた。
    `idol_service._validate_refs` とその兄弟は、エラーだと判断する前に呼び出し元が結果を調べて上書きする必要がある
    ので、意図的にセンチネルを返す形を保っている。このグループの削除／割り当て解除の関数はすべて今、
    `Literal[True]` ではなく、削除／紐づけ解除した ORM オブジェクト自体を返すので、実際の行を必要とする呼び出し元が
    使える。
24. ~~**`{"msg": "..."}` を返すルーターがすべて素の `dict[str, str]` で、OpenAPI に文書化されたスキーマとして見えて
    いなかった**~~ — **修正済み**。`app/schema/common.py::MessageResponse` を追加し、そのようなエンドポイントを
    すべて（22 のルーターファイルにわたる 40 件）`response_model=MessageResponse` に切り替えた。
    `/account/login`/`/account/refresh`/`/profile/logout` は生の `JSONResponse` のまま（Cookie の処理、または `msg` と
    並ぶ追加のフィールドのため）。フロントエンドから見える本当の変更が 1 つ:
    `products.py::delete_existing_product` は `{"msg": ...}` ではなく `{"detail": ...}` を使っていた — 今は兄弟のすべての
    エンドポイントと一致するので、そこで `response.detail` を読んでいるクライアントは `response.msg` に切り替える必要が
    ある。
25. ~~**さらに 4 つのルーター関数が `response_model` なしで生の `dict` を返していた**~~ — **修正済み**。
    `cart.py::check_cart`、`products.py::search_existing_product`/`paginated_product`/`filter_product` は今、本物の
    `response_model`（`CartDetailRead`、`ProductWithCategoryRead`、`ProductsPageRead`）を宣言する。
    `ProductWithCategoryRead` は `ProductRead` の変更ではなく新しいスキーマである — `ProductRead.category` は解決済みの
    名前（`str`）で、これら 3 つの関数は `Category` のリレーションシップが付いたままの生の `Product` の行を返すので、
    それらには `CategoryRead` を直接埋め込むのが正しい。`POST /cart/add_cart` にも同じ根本的な隙間がある
    （`response_model=None` でオプトアウトし、生の `Cart` オブジェクトを返す）が、ここでは触れていない。
26. ~~**`-> dict[str, Any]` と型付けされた残りのサービス関数はすべて素の dict を組み立てて返し、HTTP の境界で
    `response_model=` がそれをスキーマに整形することに頼っていた**~~ — **修正済み**。7 つのサービスファイルにわたる
    21 の関数が今、本物のスキーマのインスタンスを組み立てて返す — どれもすでに対応するスキーマと、ルーターでの
    `response_model=` を持っていた。`product_service._build_product_cards` が `list[dict]` ではなく
    `list[ProductCard]` を返すようになったことは波及効果を持った: カードを dict のキーで読んでいた呼び出し元
    （`get_product_detail` のおすすめのロジック、`group_service.get_group_detail` のアーティストのフィルタ）は属性アクセスに
    切り替えた。`ProductCard` は意図的に `from_attributes` の設定を持たない — 常に解決済みの値から手で組み立てられ、
    生の ORM の行から検証されることはない。これはユニットテストの落とし穴も浮き彫りにした: `MagicMock` はあらゆる
    属性アクセスを自動生成するので、`from_attributes` のスキーマの「属性がない → デフォルトを使う」というフォール
    バックが働かない — `debut_date`/`created_at`/などを明示的に設定していなかったモックは、以前は黙って通過していたが、
    サービスが本物のスキーマを組み立て始めると検証に失敗した。共有のモックのファクトリが、対象のスキーマが必要と
    するすべてのフィールドを設定するようにして修正した。
27. **メール送信を `BackgroundTasks` から Celery に移し、認証だけでなくそれ以外にも広げた**。
    `email_verification_process` は以前 `BackgroundTasks.add_task` で発火していた — リクエストスコープのフローなら
    問題ないが、`lottery_draw_service.draw_lottery` はそれ自体が Celery タスクで、`BackgroundTasks` をぶら下げる
    リクエストがないので、その当選／落選／支払いのリマインダーの通知には対応するメールがなかった。すべてのメール
    送信（認証、注文の受付、チケットの確定、抽選の当選、抽選の落選、抽選チケットの支払いの確定）は今、各呼び出し
    箇所で `celery_app.send_task(...)` によって送られる 1 つの `app.tasks.email.send_email` Celery タスクを通る。件名／
    本文のテキストはインラインの f 文字列から、`app/utils/email_templates.py` の `EmailTemplate` enum に移した。
    メールごとに 1 つのメンバーで、`.subject` と `.render(**fields)` を持つ。これを組み込む過程で 2 つの本当のバグを
    見つけた: `app/tasks/email.py` のタスク関数が、呼んでいる `send_email` ヘルパーと同じ名前だったので、自分の
    インポートを覆い隠し、何かを送る代わりに自分自身を再帰的に呼んでいた。そして `app/celery_app.py` の `include` の
    リストに新しい `app.tasks.email` モジュールが載っていなかったので、ワーカーがタスクを見つけることは決してなかった。
28. **Redis のキャッシュを商品一覧の先へ、認証不要で個人化されていない他のすべてのページ単位の読み取りに広げた**:
    `GET /concerts/events-page`、`GET /idols/members-page`、`GET /groups/groups-page`、`GET /venues/all`、
    `GET /idol_colors/all`。既存の商品キャッシュ（`app/cache/cache_service.py`）と同じ形: msgpack でシリアライズ、
    TTL 5 分（`_TTL_SECONDS`）、キャッシュされたページを変えうるすべての追加／更新／削除／再有効化で無効化し、
    それは更新系のサービス呼び出しが成功した直後にルーターから呼ぶ — サービスの中からではない。`cache_service.py` は
    読み取り側のためにすでにこれらのサービスをインポートしており、サービスがそれをインポートし返すと循環インポートに
    なるからである。`groups-page` の `member_count` と `members-page` のアクティブなグループのフィルタは、それぞれ
    *もう一方の* ドメインの行に依存しているので、アイドルの追加／更新／削除／再有効化は両方のキャッシュを無効化し、
    グループの追加／更新／削除／再有効化も同様である。会場／メンバーカラーの編集は、`events-page` に埋め込まれた
    `VenueRead` や、アイドルに埋め込まれたカラーの 16 進数値を無効化 **しない** — お金に関わらない見た目のフィールドで
    の（最大 5 分の）古さを許容しており、商品キャッシュが項目 21 ですでに行い文書化したのと同じトレードオフで、ここ
    ではそれ以上追いかけていない。
29. **同じキャッシュを、マネージャー／管理者のすべての設定ページに広げた**: `GET /idols/manager-idols-page`、
    `GET /idols/manager-idol-form-page`、`GET /groups/manager-groups-page`、`GET /concerts/manager-events-page`、
    `GET /products/manager-products-page`、`GET /products/manager-product-form-page`、`GET /management_companies/all`。
    項目 28 と同じ TTL + 書き込み時に無効化する形。これらは空の結果で 404 になることはない（新しい事務所の空の商品
    一覧は普通の状態）ので、ストア向けのページと違い、キャッシュの前後で扱う `None` の分岐はない。事務所ごとに
    キーを分けているのは 2 つの商品ページだけ（`products:manager_products_page:<company_id|"all">`）で、それはこれらが
    スコープされている唯一のものだからである — マネージャーのキャッシュされたページが、他の事務所のものや管理者の
    フィルタなしの表示に漏れてはならない。その `company_id` は `Product` 自体のカラムではない（`album_details`/
    `merch_details` を通じて間接的に解決される）ので、無効化は、ある書き込みが実際にどれに触れたかを計算するのでは
    なく、`redis_client.keys(...)` ですべての事務所のキーを消す — O(N) のスキャンで、このプロジェクトのキーの数なら
    問題ないが、トラフィックの多いデプロイでそのままにしたいものではない。アイドル／グループ／メンバーカラーの変更は、
    それらの行を埋め込んでいるマネージャーページ（アイドル／グループのフォームのドロップダウン、カラーの選択肢）を
    相互に無効化する。項目 28 のメンバー／グループの相互無効化と同じ理由付けである。当時、これらの GET エンドポイントは
    どれも認証をチェックしていなかった。6 つの `manager-*-page` は今はチェックする（項目 48）。
    `/management_companies/all` は設計上公開のまま（事務所名だけで、選択肢用、`api-spec_JP.md`）。
30. ~~**`POST /order/checkout` が、モック決済が拒否された場合でも「ご注文を受け付けました」とメールしていた**~~ —
    **修正済み**。`OrderService.checkout` はアプリ内の `order_confirmation` 通知を正しく
    `payment.status == PaymentStatus.success` で制御しているが、ルーターの `EmailTemplate.ORDER_PLACED` の送信には
    そのような制御がなかった — 例外でない戻り値ならいつでも発火し、拒否（`simulate_succ=false`）は送出せず、単に
    `order.status = cancelled` にして普通に戻る。monolith の README のために購入のフローを書いている途中で見つけた。
    `order.status == OrderStatus.cancelled` のときはメールを省くことで修正した。対応するチケットの経路
    （`ticket_service.checkout_ticket`）にはこのバグはなかった — そのメール送信は、ルーターではなくサービスの中の、
    通知と同じ `if payment.status == PaymentStatus.success:` ブロックの中にすでにある。
31. **同じキャッシュをアイドル／グループの詳細ページに広げた**: `GET /idols/{id}/detail`、`GET /groups/{id}/detail`。
    項目 28/29 と同じ TTL + 書き込み時に無効化する形だが、1 つの共有キーではなく ID ごとのキー（`idols:detail:<id>`、
    `groups:detail:<id>`）で、各 ID がそれぞれのキャッシュエントリになる。アイドルの詳細ページはそのグループと兄弟
    （同じ `group_id` を持つ他のアイドル）を埋め込み、グループの詳細ページはすべてのメンバーのアイドルのデータを埋め
    込む — そのため、どちらの側への書き込みも、その書き込みが直接扱わない ID をキーにした詳細ページを無効化しうる
    （グループの改名では、更新のエンドポイントが ID を知ることのないアイドルのキャッシュを破棄しなければならない）。
    毎回の書き込みの前にどの ID が `group_id` を共有しているかを解決するのではなく、
    `CacheService.delete_cached_idol_details`/`CacheService.delete_cached_group_details` はそれぞれ
    `redis_client.keys(...)` で名前空間全体を消す。項目 29 のマネージャーの商品の無効化と同じ O(N) のスキャンの
    トレードオフ — どちらの側の書き込みも両方のキャッシュに影響しうるので、アイドルとグループのすべての変更
    （追加／更新／削除／再有効化／画像のアップロード）から一緒に呼ばれる。
32. **`cache_service.py` を関数を並べただけのモジュールから `class CacheService`（すべて `@staticmethod`）に変換した**。
    `architecture_JP.md` §2 の 2 番で文書化しているルーター／サービス層の規約に合わせたもの — 9 つのファイルにわたる
    すべての呼び出し元は今、各関数を名前でインポートする代わりに `CacheService` をインポートし、
    `CacheService.get_cached_x(...)`/`CacheService.delete_cached_x(...)` を呼ぶ。`cache_service.py` の外に残っていた
    `redis_client` の直接の呼び出しを洗い出す中で、`products.py` に 2 か所（`add_new_product`、
    `add_new_product_with_detail`）見つけた。これらは、`products:store_page` も消す
    `CacheService.delete_cached_products()` を通さずに、`redis_client.delete("products:list")` を直接呼んでいた。
    どちらも `/products/all` のキャッシュしか消していなかったので、どちらかのエンドポイントで追加された商品は、ストア
    ページのキャッシュされた商品一覧を最大 5 分古いままにしていた。両方を `CacheService` 経由にした副作用として、今は
    修正されている。`rate_limit.py` の Redis の直接の呼び出し（今は `SET NX` + `INCR` のトランザクション、その後
    `ttl`）は意図的にそのままにした — 固定ウィンドウのレート制限はページのキャッシュとは別の関心事で、経由させる
    べき `CacheService` の対応物がない。
33. **`GET /products/{id}/detail` と `GET /concerts/{id}/detail` をキャッシュした**。どちらもフロントエンドから
    ホットパスとして報告されたもの（`ProductDetailPage.vue`/`EventDetailPage.vue`）。商品のほうは項目 31 の形を
    そのまま拡張したもの: `products:<id>:detail` で、すべての商品の変更のエンドポイントから無効化する（名前空間全体。
    アイドル／グループの詳細と同じ波及の理由付け — おすすめは他のすべての商品から引いてくる）。

    公演のほうはそう単純ではない: `ConcertDetailRead` は公開の公演／会場／券種／ラインナップ／キャンペーンのデータと
    並んで `has_ticket`/`has_won_lottery`/`entered_campaign_ids`/`my_lottery_preferences` をまとめており、この 4 つの
    フィールドは閲覧者ごとのものである — レスポンスをそのままキャッシュすると、あるファンのキャッシュヒットで別の
    ファンのチケット／抽選の状態が漏れてしまう。`concert_service.get_concert_detail`（削除）を、
    `get_concert_detail_public`（公演／会場／券種／ラインナップ／出演グループ／キャンペーンだけで、個人化された
    フィールドはスキーマのデフォルトの False／空のまま — これが `CacheService.get_cached_concert_detail` が
    `concerts:<id>:detail` にキャッシュする部分）と `get_personalization`（閲覧者ごとの 4 つのフィールドで、毎回の
    リクエストで新たに計算し、決してキャッシュしない）に分けることで修正した。`get_concert_detail_by_id` は、ファンが
    ログインしているときだけ `result.model_copy(update=...)` でそれらをマージする。ゲストはキャッシュされたものを
    そのまま受け取る。より単純な代替案（ログイン中のファンについてはキャッシュを完全に飛ばす）ではなくこちらを選んだ
    のは、チケット／抽選の状態のために毎回のリクエストで小さなキャッシュなしのクエリを 1 つ払う代わりに、ログイン中の
    トラフィックでもキャッシュヒット率を保てるからである — `get_cached_store_page` と同じ形。

    アイドル／グループの名前空間全体の無効化とは違い、公演のキャッシュされたまとまりを変えうるすべての書き込み（公演
    自体、その券種の 1 つ、抽選／一般販売のキャンペーン、出演者のクレジット）はすでに自分の `concert_id` を知っている
    （または、`ticket_type_id` しか持たないキャンペーンについては `TicketTypeService.get_ticket_type` で解決できる）ので、
    `CacheService.delete_cached_concert_detail(concert_id)` は正確な単一キーの削除で、`concert.py`（更新／キャンセル／
    出演者の割り当て／割り当て解除）、`ticket_type.py`（追加／更新／削除）、`lottery_campaign.py`、
    `direct_sale_campaign.py`（どちらも追加／更新／削除）に組み込まれている。

    **既知で許容している隙間、ここでは修正していない**: `TicketType.sold_quantity` と抽選キャンペーンの
    `entry_count`/`status` は、チケットの購入（`ticket_service`、`payment_service`）と抽選（`lottery_draw_service`、
    Celery ワーカーで非同期に実行）の間に変わる — どちらもこのキャッシュを無効化しないので、公演の表示上の残数／応募数
    は、購入や抽選の後、最大 5 分遅れることがある。意図的にそれらのフローの中まで追いかけていない: 項目 21 の商品
    キャッシュのバグとは違い、これが売り越しのリスクになることは決してない（`ticket_service`/`payment_service` の実際の
    キャパシティのチェックは、キャッシュではなく DB の現在の状態を読む）— 表示だけの古さであり、項目 28 の許容した
    会場／メンバーカラーの古さと同じ種類だが、見た目のフィールドではなくチケットの残数に関わるので、明示的に挙げて
    いる。
34. **結合テストのカバレッジの取り組み**。本物の Postgres + Redis（既存のローカルの `i-dolly-backend` Docker Compose
    プロジェクトの `postgres`/`redis` コンテナで、新しい環境ではなく、すでにビルドされた `i-dolly-backend-app` の
    イメージから動かした）に対して実行した — この項目のすべてのテストは静的に検証しただけでなく実際に実行しており、
    §3 のとおり、それ以外では稼働中の DB に到達できないセッションで結合テストについてそれが可能になったのはこれが
    初めてである。`tests/integration/identity/test_profile.py`（`/profile/me`、`/change-password`、
    `/forgot-password`、`/set-password`、`/logout`、`/make-admin`、`/create-manager`）と `test_account.py`
    （`/account/refresh`、`/verify-request`、`/verify`）、`tests/integration/events/test_venues.py`（`/venues` の完全な
    CRUD）、`tests/integration/shared/test_notifications.py`（4 つすべての `/notifications/*` エンドポイントで、
    `type="password_reset"` の行を直接投入 — order/ticket/lottery_entry/concert の FK を必要としない唯一の通知の種類）、
    `tests/integration/marketplace/test_payment.py`（`/payment/status/*`、加えて `create_order`/`capture_order`/
    `verify_webhook_signature` をモックした `/payment/paypal/capture` と `/payment/paypal/webhook` — 本物の PayPal
    サンドボックスの呼び出しはない）を追加した。`tests/integration/test_permissions.py`（既存の `Factory` を再利用）を、
    `/lottery_preferences/*`、`/apply` 以外の `/lottery_entries/*`、`/checkout` 以外の `/tickets/*` で拡張した。

    **途中で見つけて修正したもの**: `UserService.promote_admin`（`/profile/make-admin` の裏側）は、非推奨の `is_admin`
    カラムしか設定しておらず、`role` は決して設定していなかった — しかし `require_admin` がチェックするのは `role` で
    あり、`database-design_JP.md`/`architecture_JP.md` はそれを実際の正となる情報源としてすでに文書化している。その
    ため、それを行う唯一のエンドポイントでユーザーを昇格させても、そのユーザーは以前と同じく管理者のルートに到達
    できないままだった。今は両方を設定する（そのカラムはまだ削除されていないので、`is_admin` も設定し続ける）。
    `test_profile.py` のリグレッションテスト（`test_make_admin_promotes_role_not_just_the_deprecated_flag`）で捕まえた。
    これは、`role` がトークンに焼き込まれるのではなくリクエストごとに DB から新たに読まれるので、昇格したユーザーの
    *既存の* アクセストークンがすぐに管理者のアクセス権を得ることをアサートする。古い `is_admin` だけのチェックを
    試していた 2 つのユニットテスト（`test_user_service.py`）はそれに合わせて更新した。

    **ここではカバーしておらず、まだ未解決**: 実際に認証されたマネージャー／管理者としてのグループ／アイドルの CRUD の
    *成功* の経路（`test_permissions.py` の `Factory` には `group()` のビルダーがなく、既存のグループ／アイドルのテスト —
    ドメインごとに分かれた `test_main` のファイルにある — はどれも 401/403/404 の RBAC の境界までしか到達せず、本当の
    200 には至らない）。`/payment/status/order/{id}` の見つかった場合（本物の `/order/checkout` の裏に、商品／カート／
    配送先住所の完全なチェーンが必要で、ここでは作っていない — 401/404 の経路だけをカバーしている）。どちらも §5 を
    参照。
35. **すべての単純な読み取りのサービスメソッドで `Object | Literal[False]` → `Object | None`**（約 60 のメソッド、23 の
    サービスファイルと `cache_service.py`）。`None` は Python における本来の「何もない」を表す値であり、
    `db.get(...)`/`.first()` が見つからなかったときにすでに返す値なので、それらをラップする読み取りに、同じ意味の
    2 つ目の偽の値はもう必要ない — `architecture_JP.md` §2 の更新された規約の注記を参照。他の文字列の結果と並んで
    たまたま `False` を含む複数値のセンチネル（`product_service.update_product` の
    `Literal[False, "forbidden", "price_locked", "category_not_found"]` など）は意図的にそのままにした — それは別の、
    今も有効なパターン（`architecture_JP.md` §2 の「プライベートな複数値のヘルパー」のケース）で、この項目が触れた
    ものではない。`if not result:` をチェックしている呼び出し元はどれも変更が不要だった（`None` と `False` はどちらも
    偽）。明示的に `is False` を使っていたルーター／テストは `is None` に更新した。

    **途中で 2 つの本当の衝突を見つけた** — 同じ関数の中で、`False` と `None` がすでに 2 つの *異なる* 役割を果たして
    いたケースで、改名するとそれらが黙って 1 つに統合され、呼び出し元が頼っていた情報が失われるところだった:
    - `OrderService.cancel_placed_order` は、「注文が見つからない」に `None` を、「見つかったが、すでに発送済み」に
      `False` を返していた — `order.py` のルーターはそれらをそれぞれ 404 と 400 にしていた。2 つ目の偽の値を返す
      代わりに、「すでに発送済み」のケースで `BadRequestError` を送出して修正した。`architecture_JP.md` がこれについて
      すでに文書化している例外階層の規約に合わせたもの。ルーターは今、そのエンドポイントで `ServiceError` を捕捉する。
    - `CartService.add_to_cart` は、「在庫不足／商品が見つからない」に `None` を、「ユーザーが見つからない」に `False` を
      返していた（実際には到達しない — `user_id` は常にすでに検証済みの `get_current_user` から来るが、ルーターは
      それでもそれで分岐していた）。同じ修正: 2 つ目の偽の値の代わりに `NotFoundError`。

    どちらの衝突もテストでは捕まらなかった — 「すでに発送済み」の 400 の経路も、（実際には到達しない）「ユーザーが
    見つからない」の経路も、試しているものがなかったので、機械的な改名をしていたら、赤いテストが 1 つも出ないまま、
    両方の `HTTPException` の分岐が黙ってデッドコードになっていた。代わりに、何かを実行する前のレビューの間に、各
    ルーター自身の `is False`/`is None` の分岐を読んで見つけた。その後クリーンであることを確認した: ユニット
    393/393、結合 232/232（後者は項目 34 のとおり本物の Postgres/Redis のスタックに対して）。

36. **identity/events/shared にわたって、ハードコードされた値の集合の文字列 → `class X(str, Enum)`。マーケットプレイスで
    `OrderStatus`/`PaymentStatus`/`ShippingStatus` がすでに使っていたパターンに合わせた。** それまでは、ステータスの
    カラムを本物の Python の enum クラスで裏付けていたのはマーケットプレイスだけで、他のすべてのドメインは Python 側の
    型を持たない素の SQLAlchemy の `Enum("a", "b", "c", name=...)` を使い、サービスのコードは呼び出し箇所に散らばった
    生の文字列リテラルと比較していた（`current_user.role == "manager"`、`ticket.status = "paid"`、
    `NotificationService.create_notification(db, user_id, "order_confirmation", ...)` など）— そのどれかでタイプミスが
    あれば、境界で捕まる検証エラーではなく、黙って何もしないか、コミット時の `IntegrityError` になっていた。モデルの
    カラムごとに 1 つの新しいクラスを、そのフィールドの Read/Update モデルをすでに持っているスキーマファイルに置いた
    （`architecture_JP.md` §2 を参照）: `UserRole`（`schema/identity/user.py`）、`TicketTier`/`SaleMethod`
    （`schema/events/ticket_type.py`）、`ConcertStatus`（`schema/events/concert.py`）、`CampaignStatus`
    （`schema/events/lottery_campaign.py`）、`DirectSaleCampaignStatus`（`schema/events/direct_sale_campaign.py`）、
    `LotteryEntryStatus`（`schema/events/lottery_entry.py`）、`TicketStatus`（`schema/events/ticket.py`）、
    `NotificationStatus`/`NotificationType`（`schema/shared/notification.py`）、`ReleaseFormat`
    （`schema/marketplace/album_detail.py`）。すべてのモデルの `Column` は今、素のインラインの値のリストではなく、対応する
    クラスを使う（`Column(Enum(TicketStatus, name="ticket_status_enum"))`）。`server_default=` は Python のデフォルト値
    ではなく DDL のテキストなので、素の文字列ラベルのまま — 下にある Postgres の enum 型とラベルは変わらないので、
    マイグレーションは不要。触れたサービス／ルーターのファイル（約 30 ファイル: すべての `_manager_scope_violation`
    ヘルパー、`require_admin`/`require_manager_or_admin`、購入／決済／抽選のステータスの遷移、すべての
    `NotificationService.create_notification(..., notification_type=...)` の呼び出し箇所）にわたるすべての比較と代入は、
    今は生の文字列ではなく enum のメンバーを使う。意図的にそのままにしたもの: 前の項目の注記がすでに除外している
    センチネルを返す文字列（`Literal["forbidden", "not_found"]` などの複数分岐の関数の結果 — モデルのカラムの値の集合
    ではない）と、すべてのテストファイル。`str, Enum` のメンバーは素の文字列と等しいと比較され、既存のテストは、すでに
    enum を持っていたフィールド（`OrderStatus`/`PaymentStatus`）についてリテラルの文字列と enum のメンバーをすでに混在
    させているので、これを 22 ファイルにわたる約 280 か所のテストファイルに広げても、挙動の変化のない純粋な手間に
    なるだけだった。クリーンであることを確認した: ユニット 393/393、結合 232/232（項目 34 のとおり本物の Postgres/
    Redis のスタック）。

37. **項目 23 が残した隙間を閉じた: 項目 23 の一掃が対象にした古い `_raise_for`/`_raise_for_link` のルーターの
    ヘルパーを通っていなかったために、送出せずにまだ `Literal["forbidden", "not_found", ...]` のセンチネルを返していた
    6 つのサービスメソッド。** 他のすべての場所と同じ `NotFoundError`/`ForbiddenError`/`BadRequestError` の階層に変換した:
    `UserService.create_manager_user`、`ProductService.add_product_with_detail`/`update_product`/`set_product_image`/
    `delete_product`/`get_product_sales_page`、そして `LotteryDrawService.draw_lottery`（ルーターではなく
    `app/tasks/lottery.py` の Celery タスクから呼ばれる — そこで捕捉されない `ServiceError` はタスクを失敗させるだけで、
    これは以前の誰も読んでいなかった文字列のセンチネルより厳密に多くの情報を持つ。`PUT /concerts/lottery-draw/{id}` は
    投げっぱなしで、タスクの戻り値を調べることは決してなかったからである）。`draw_lottery` の戻り値の型は、早期
    リターンがどれも `dict` に一致しない素の文字列だったのに `-> dict` だった — 今は `-> LotteryResult` で、成功時は
    型のない dict のリテラルではなく本物の `LotteryResult(...)` のインスタンスとして組み立てる。すべてのルーターの
    呼び出し元は今、`if result == "...":` のチェックの連鎖の代わりに、1 行の `except ServiceError as e: raise
    HTTPException(status_code=e.status_code, detail=str(e)) from e` を行う。意図的なステータスコードの変更が 1 つ:
    `add_product_with_detail` の `category_not_found`/`owner_not_found`（POST のボディ内の不正な FK の参照）を 400 から
    404 に変えた。このコードベースで他のすべての「参照された行が存在しない」ケースがすでに扱われている方法に合わせた
    もの（`concert_service.add_concert`、`lottery_campaign_service.add_campaign` などはすべて、まさにこの形について
    `NotFoundError` を送出する）— 古い 400 をテストしているものは何もなかったので、これは文書化された契約を壊すのでは
    なく、本当の不整合を直したものである。`artist_inactive` は `BadRequestError`/400 のまま（参照の欠如ではなく状態の
    問題）、`forbidden`/`price_locked` は `ForbiddenError`/403 のまま。どちらも以前から変わらない。

    意図的に触れなかったもの: `idol_service._validate_refs` — 依然としてセンチネルを返し、そうあるべきである。これは
    プライベートなヘルパーで、その呼び出し元（`add_idol`/`update_idol`）は、エラーだと判断する前にその結果を調べて、
    ときには上書きする必要がある（`update_idol` は、アイドルがグループの無効化の前からすでにそのグループにいた場合、
    `"group_inactive"` をエラーではないものとして扱う）。すぐに `raise` される例外ではそれを表現できない —
    `docs/architecture_JP.md` §2 はすでに、これを見落としではなく「センチネルを返さずに送出する」ルールの唯一の正当な
    例外として文書化している。ただし、そのセンチネルの値自体は依然として素の `Literal["company_not_found", ...]`
    だったので、追加対応として、今は `idol_service.py` のヘルパーの隣に置いたローカルな `class _RefIssue(str, Enum)` に
    なっている — これはモデルのカラムの値の集合ではなく、2 か所（`add_idol`/`update_idol`）で比較されるプライベートな
    ヘルパー自身の複数分岐の結果にすぎないので、`app/schema/` ではない。項目 36 の enum の一掃と同じ動機（メンバー名の
    タイプミスは、`if error == "...":` の分岐に黙って決して一致しない文字列ではなく、捕まる `AttributeError` になる）を、
    `Column` ではなかったために項目 36 が届かなかった唯一のセンチネルを返すケースに適用したもの。挙動の変化はない —
    このヘルパーの内部の戻り値ではなく、その周りで送出される公開の `NotFoundError`/`BadRequestError` をすでにアサート
    していた既存の `add_idol`/`update_idol` のテストで確認した: ユニット 393/393、結合 232/232（項目 34 のとおり本物の
    Postgres/Redis のスタック）。

38. **偽または非 `None` だとすでにわかっている結果を再チェックし、クエリをそのまま返すのと決して違う挙動をしえない
    分岐を加えていた、約 33 の本当の読み取りメソッドを簡略化した。** 2 つの形:
    - 素の `list[X]` を返す読み取り（`result = db.query(X)...all(); if not result: return None; return result`）は
      `return db.query(X)...all()` にまとめ、型は `list[X] | None` ではなく `-> list[X]:` とした。`.all()` は `None` では
      なく常に `[]` を返し、ルーターの既存の `if not result: raise HTTPException(404, ...)` にとって `[]` は `None` と
      まったく同じく偽なので — 1 つのルーター（下記）を除くすべてのルーターについて、これは挙動の変化ではなく純粋な
      簡略化である。
    - `db_x = db.get(X, id); if not db_x: return None; return db_x`（間に他のロジックなし）だけの単一オブジェクトの
      読み取りは、直接 `return db.get(X, id)` にまとめた。型は `X | None` のまま — リストの場合と違い、
      `.get()`/`.first()` は本当に `None` を返しうる。
    26 ファイル: `concert_service`（`get_concerts`/`get_performers`/`get_all_performers`）、`idol_service.get_idols`、
    `group_service.get_groups`、`venue_service.get_venues`、`ticket_type_service.get_ticket_types`、
    `lottery_campaign_service.get_campaigns`、`direct_sale_campaign_service.get_campaigns`、`lottery_entry_service`
    （`get_my_entries`/`get_entries_for_campaign` — 既存の `NotFoundError`/`ForbiddenError` の事前チェックは残し、最後の
    リストの返却だけを簡略化した）、`lottery_preference_service.get_my_preferences`、
    `management_company_service.get_companies`、`position_service`（`get_positions`/`get_idol_positions`/
    `get_all_idol_positions`）、`idol_color_service.get_idol_colors`、`merch_detail_service.get_merch_details`、
    `album_detail_service.get_album_details`、`genre_service`（`get_genres`/`get_album_genres`/`get_all_album_genres`）、
    `category_service.get_categories`、`product_service.list_of_products`、`payment_service`（`fetch_payment_status`/
    `fetch_ticket_payment_status`/`fetch_all_payments`）、`order_service.fetch_single_placed_order`（と
    `get_user_shipping_status`。行そのものではなく、問い合わせた行から `.shippingstatus` を取り出すので、1 行の三項演算に
    書き直した）、`shipping_service`（`fetch_address`/`get_address_by_id`）、`notification_service.get_my_notifications`、
    `ticket_service.get_my_tickets`。

    **意図的に触れなかったもの**: クエリの結果を返す前により大きな Pydantic オブジェクトで包む読み取り
    （`get_events_page`、`get_members_page`、`get_group_detail`、`get_idol_detail`、`get_groups_page`、
    `get_concert_detail_public`、`get_store_page`、`get_product_detail`、`cart_service.see_cart`、
    `product_service.search_product`）。Pydantic モデルのインスタンスは `__bool__`/`__len__` を持たず常に真なので、
    それを組み立てる前の `if not entity: return None` だけが、ルーターが「何もない」と「見つかった」を区別できる
    *唯一の* 手段である — そのチェックをまとめて消すと、すべての空の結果が、404 ではなく、半分しか組み立てられて
    いないページを持つ 200 に黙って変わってしまう。`authenticate_user`/`verify_refresh_token`（クエリと返却の間に本当の
    検証のロジックがあり、冗長な再チェックではない）と、プライベートなヘルパー `idol_service._validate_refs`/
    `ticket_service._existing_live_ticket`/`_unresolved_lottery_entry` についても同じ理由付けである。

    **リストの形の変更についてルーターの呼び出し元を監査していて、本当のバグを 1 つ見つけた**:
    `router/marketplace/payment.py::check_payment_status_all` は `fetch_all_payments` の結果に対して
    `if payment is None:` をチェックしていた — 古い `list[Payment] | None` に対しては正しかったが、新しい
    `list[Payment]` に対しては黙って間違っていた（空のリストは決して `None` ではないので、決済が 0 件のユーザーは
    意図された 404 ではなく `[]` 付きの 200 を受け取っていた）。兄弟のすべてのルーター自身のチェックに合わせて
    `if not payment:` に修正した。他のすべての呼び出し元（ルーターと、`list_of_products`/`get_venues`/`get_idol_colors`/
    `get_companies` を包む `CacheService` 自身のラッパー）は、`is None` のチェックではなくすでに偽のチェックを使って
    いたので、変更は不要だった。

    テストへの影響: 変換したリストを返すメソッドのすべての `test_*_empty` のユニットテストは `result is None` を
    アサートしていた。約 27 件すべてを `result == []` に切り替えた（HTTP の境界での挙動は同じ — `[]` と `None` は
    どちらもルーターの `if not result:` にとって依然として偽である）。クリーンであることを確認した: ユニット 393/393、
    結合 232/232（項目 34 のとおり本物の Postgres/Redis のスタック）。

    古いセンチネルの値をアサートしていたすべてのテスト（`test_lottery_draw_service.py` ×6、
    `test_product_service.py` ×4、`test_user_service.py` ×3）は `pytest.raises(...)` に切り替えた。クリーンであることを
    確認した: ユニット 393/393、結合 232/232（項目 34 のとおり本物の Postgres/Redis のスタック）。

40. ~~**ユニットテストが SendGrid を通じて本物のメールを送っていた**~~ — **修正済み**。重なり合う 2 つのバグ:
    - `app/utils/email_sender.py::send_email` は `settings.DEBUG` を開発用のバナーを出力するためだけに使っていた — その
      後も、ローカルの `SENDGRID_API_KEY` は常にプレースホルダーなので本物の送信は無害に失敗するだけ、という前提で、
      いずれにせよ本物の SendGrid の API を呼んでいた。その前提は、本物のキーがローカルで設定されると（例: メールの
      フローをエンドツーエンドでテストするため）成り立たず、それがまさにこのプロジェクトの実際のローカルの設定
      だった: `DEBUG=true` *かつ* 本物のキー。開発用のバナーを出力した直後に、そのまま進まずに `return` することで
      修正した。
    - `tests/unit/events/test_lottery_draw_service.py` の当選／落選のテストは `celery_app.send_task` をモックしていな
      かった（すでにモックしていた `test_user_service.py`/`test_auth_service.py` とは違い）ので、`draw_lottery` が生み
      出すすべての当選者／落選者が、本物の `LOTTERY_WON`/`LOTTERY_LOST` のメールタスクをキューに入れていた — それが、
      同じ Redis のブローカーを消費する本物のワーカーと上の `send_email` のバグによって、実際に配信されていた。その
      1 ファイルにパッチを当てるのではなく根本から修正した: `tests/unit/conftest.py` の新しい autouse のフィクスチャが
      すべてのユニットテストについて `app.celery_app.celery_app.send_task` をモックするので、このテストであれ将来の
      テストであれ、自分でモックすることを覚えているかどうかにかかわらず、本物の Celery の送信に到達することは
      できない。`tests/conftest.py` の既存の `fake_redis` のパッチと同じ、多層防御の理由付けである。

    `sendgrid.SendGridAPIClient.send` を、呼ばれたら送出するように一時的に細工してユニットテストスイート全体を実行
    することで検証した — 393/393 が成功し、何もそこに到達しないことを確認した。2 つ目の修正（`send_email` の DEBUG
    による早期リターン）を、ここから稼働中の SendGrid のアカウントに対して検証する方法は `docs/` にはない。代わりに
    安全だと判断した。`email_sender.py` を直接試すテストはなく、この変更は、以前は黙って失敗していた（プレース
    ホルダーのキー）か、そもそも実行されるべきでなかった（本物のキーで、それが実際のバグだった）分岐を早期リターン
    させるだけだからである。

41. ~~**トランザクションメールを SendGrid から Resend に移行した**~~ — **修正済み**。`app/utils/email_sender.py` は今、
    `SendGridAPIClient.send(...)` ではなく `resend.Emails.send(...)` を呼ぶ。`send_email(to_email, subject, body)` の
    シグネチャも、`settings.DEBUG` による開発用の早期リターン（項目 40）も同じ。`Settings.SENDGRID_API_KEY` はなくなり、
    `RESEND_API_KEY` に置き換わった。`FROM_EMAIL` は変わらないが、任意のアドレスではなく、Resend で検証済みのドメイン
    （またはサンドボックスの `onboarding@resend.dev`）上のものでなければならなくなった。`requirements.txt`、
    `.env.example`、CI（`.github/workflows/test.yml` の 2 か所の `SENDGRID_API_KEY` のシークレットの参照）、`render.yaml` を
    すべてそれに合わせて更新した。

    `render.yaml` を更新しているときに、この移行とは無関係の既存の隙間を見つけた: `i-dolly-backend-worker` サービスの
    `envVars` には `SENDGRID_API_KEY`/`FROM_EMAIL` がまったく含まれていなかった（Web サービスだけが持っていた）。実際に
    `app.tasks.email.send_email` を実行するプロセスはワーカーで、`Settings` にはそのキーのデフォルトがないにもかかわらず
    — そのため、この設定から最後に（再）デプロイされたときには、ワーカーのコンテナは Render 上で起動に失敗していた
    はずである。この変更の一部として、ワーカーの `envVars` に `RESEND_API_KEY`/`FROM_EMAIL`/`DEBUG` を追加した。次の
    本当の Render のデプロイで、ワーカーが実際に何か別の方法で（例: このエクスポートされたファイルと同期していない、
    ダッシュボードでの手動の設定で）これらを得ていたのかを確認する価値がある。

    検証: `py_compile` + `ruff check --select F401,F811,F821` はクリーン。ユニットテストスイート全体（393/393）は影響を
    受けない。項目 40 の autouse の `celery_app.send_task` のモックにより、どのテストもそもそも `email_sender.py` に到達
    しないからである。実際の配信をスモークテストするための稼働中の Resend のアカウントはここからは使えない — 項目 40 の
    SendGrid の検証と同じ注意点。

    **追加対応**: `i-dolly-app.site`（Cloudflare Registrar）を購入し、`mail.i-dolly-app.site` を Resend の送信ドメインとして
    検証した — DKIM（TXT）、SPF 関連の 2 つの CNAME（Resend の `forge.rmta.net` の基盤を指す `rsend.mail`/`send.mail`）、
    DMARC の TXT（`_dmarc`、`p=none`）を、すべて Cloudflare の DNS で追加し、2 つの CNAME は「DNS only」に設定した
    （Cloudflare のプロキシは HTTP(S) しか話さないので、プロキシされた／オレンジの雲の CNAME だと検証が壊れていた）。
    `.env` の `FROM_EMAIL` を `noreply@mail.i-dolly-app.site` に更新した — 以前の誤った値（`i-dolly-backend.onrender.com`。
    `@` のない素のホスト名で、そもそも有効なメールアドレスではない）も修正した。ドメインが検証されたので、送信は
    もう Resend のアカウント所有者自身の受信箱に限定されたサンドボックスではない — これで、ローカル／手動のテスト
    については上の「テストするための稼働中のアカウントがない」という注意点は解消されるが、CI とデプロイされた
    Render のサービスは、そこでも `RESEND_API_KEY`/`FROM_EMAIL` を更新しない限り、依然としてプレースホルダー／未設定の
    キーしか持たない（`render.yaml` の `sync: false` は、このファイルではなく Render のダッシュボードが本当の値を持つ
    ことを意味する）。

42. ~~**メール本文がプレーンテキストなのに Resend の `html` パラメータで送られていた**~~ — **修正済み**。
    `app/utils/email_sender.py` の `resend.Emails.send(...)` の呼び出しは、ずっと `body` を `html` フィールドとして渡して
    いた（項目 41 の SendGrid → Resend の移行以来）が、`app/utils/email_templates.py` のすべての `EmailTemplate` の本文は
    `\n\n` で区切ったプレーンテキストだった — HTML は素の改行をスペースに潰すので、どのメールも改行のない 1 つの
    続いた段落として表示され、認証／リセットのリンクはリンクではなく、クリックできない素の URL のテキストとして
    表示されていた。7 つのテンプレートすべて（`EMAIL_VERIFICATION`、`ORDER_PLACED`、`TICKET_CONFIRMED`、
    `LOTTERY_WON`、`LOTTERY_LOST`、`LOTTERY_PAYMENT_CONFIRMED`、`RESET_PASSWORD`）を本物の HTML に変換した: 段落ごとに
    `<p>`、同じ段落内の改行に `<br>`、認証／リセットのリンクに `<a href="{link}">`。埋め込まれるフィールドはどれも、
    スキーマの境界で検証される `EmailStr`（`{email}`）か、サーバーが生成した値（ID、価格、HMAC で署名された `{link}` の
    トークン）であり — 任意のユーザーのテキストはないので、プレースホルダー自体の HTML エスケープは不要だった。

    検証: `py_compile` + `ruff check --select F401,F811,F821` はクリーン。ユニットテストスイート全体（393/393）—
    メール本文の内容を調べる唯一のテスト（`test_user_service.py::test_reset_password_process`）は、リンクの部分文字列が
    存在することだけをアサートしており、それは新しい `<a href="...">` のマークアップの中でもそのまま成り立つ。

43. ~~**`orders.shippingstatus` が一度も設定されていなかった**~~ — **前提が誤っていたので訂正。本当のバグはその逆
    （行の重複）だった — 修正済み**。この項目は元々、`ShippingStatus(` を grep した結果に基づいて、`shipping_status` の
    行を挿入するものが何もないと主張していた。その grep は、モデルを `ModelShipStatus` としてインポートし、
    `PaymentService.create_payment` でずっと 1 行挿入していた（すべての購入手続きで、ステータスは決済の結果で設定）
    `payment_service.py` を見落としていた — そして `finalize_paypal_payment` は PayPal のキャプチャ時に *もう 1 行* 挿入
    していた。ここでの「修正」（`OrderService.checkout()` での 3 回目の挿入）によって、すべての注文が 2〜3 行を持つ
    ようになった。`Order.shippingstatus` が `uselist=False` で一意制約がないので、どの行が読み込まれるかは不定だった —
    拒否されたモックの注文は `pending` と `cancelled` の両方を持っていたので、`ship_order` は未払いの注文を発送できて
    しまった（`docs/bugs_JP.md` #1）。

    本当の修正: `create_payment` をその行の唯一の作成者にし、`checkout()` の余分な挿入を削除し、
    `finalize_paypal_payment` は挿入する代わりに既存の行（ステータス + `updated_at`）を更新するようにした。保険として
    マイグレーション `a9d3f5b7c1e2` が `uq_shipping_status_order_id` を追加する（重複除去のステップはない — 行を重複させる
    コードが稼働している間に作成された注文はなかった）。リグレッションのユニットテスト:
    `test_order_finalize_updates_existing_shipping_status_not_insert`。実際に検証した（2026-09-25）: 結合テストスイートの
    空の状態からの `alembic upgrade head` が `a9d3f5b7c1e2` に到達し、`uq_shipping_status_order_id` が存在し、235 件の
    結合テストすべてが成功した。

    注文の詳細ページが、発送されたことだけでなく *いつ* 発送されたかも表示できるよう、
    `ShippingStatusResponse.updated_at` も追加した（以前は `status` だけ）— これが 2 つ目の小さな問題を明らかにした:
    `shipping_status.updated_at` の `server_onupdate=func.now()` は SQLAlchemy に意図を伝えるだけで、実際の Postgres の
    トリガーの裏付けがないので、ステータスの変更で実際に更新されることは決してなかった。`OrderService.
    update_shipping_status()`（既存の管理者による自由な上書き）と新しい `ship_order()` のどちらも、それに頼らずに今は
    明示的に `updated_at` を設定する。

    検証: `py_compile` はクリーン。ユニットテストスイート全体（404/404）。`ship_order` の制御フロー（事務所をまたぐ
    マネージャーは拒否、同じ事務所のマネージャーは成功 + 通知、すでに発送済みの注文は拒否）は、このセッションでは
    いつもの使い捨ての Postgres での確認に Docker が使えなかったので、モックのセッションで試した — Docker が戻ったら、
    スキーマ／モックの層だけでなくエンドツーエンドで確認するために、購入手続き → single_placed_order の往復全体を本物の
    稼働中の DB で実行する価値がある。

44. ~~**トランザクションメールが価格をドルで表示し、チケットのメールは税抜きの価格を表示していた**~~ — **修正済み**。
    `ORDER_PLACED`、`TICKET_CONFIRMED`、`LOTTERY_PAYMENT_CONFIRMED` は金額を `${x:.2f}` と整形していたが、すべての価格は
    円の整数で、PayPal の注文は `JPY` で作成される。今は `¥{x:,.0f} (tax included)` と表示する。2 つのチケットのメールは
    `ticket_type.price`（税抜きで保存）を渡していたが、ファンに請求されるのは `with_tax(price)` である。今はチェック済みの
    `total_amount` を渡すので、メールは請求額と一致する。`ORDER_PLACED` はすでに税込みの `order.total_price` を使って
    いた。これとは別に、その素の `Status: {status}` の行（生の `OrderStatus` で、発送ステータスと読み間違えやすい）は、
    今は `Payment: Paid` / `Payment: Awaiting payment confirmation`（PayPal、まだキャプチャされていない）になっている。
    まだ未解決: 注文でもチケットでも、`finalize_paypal_payment` が PayPal の決済をキャプチャしたときに追加のメールは
    送られない。

    検証: 3 つのテンプレートすべてを int/float/`Decimal` の金額で表示した。ユニットテストスイート 444/444。本物の
    メールは送っていない。
45. **レート制限の調整**。`GET /products/store-page` のベンチマークで、その `5, 60` の予算（IP ごと）が、攻撃者だけでなく
    普通の閲覧のパターンでもほとんどすぐに使い切られることがわかったのがきっかけ。`app/router` にわたるすべての
    `rate_limit(limit, window, key_func)` の呼び出しを監査し、それぞれが実際に何を防いでいるかでまとめた: お金／在庫の
    変更（購入手続き、カート、抽選の応募 — `3/60`）と認証の悪用の対象（登録、ログイン、パスワード忘れ — `3-10/60`）は
    すでに正しく厳しかったのでそのままにした。いくつかの自己スコープの、またはキャッシュされた公開の読み取りが、
    悪用の理由付けなしに、単にコピペされた数値として同じ厳しい予算を共有していた。引き上げたもの:
    `GET /products/all`/`GET /products/store-page` `5→30`（キャッシュが裏にあり TTL 5 分で、DB はすでに守られている —
    この予算は負荷ではなくスクレイピングを防いでいたもので、1 分に 5 回は、1 つの共有 IP での通常の SPA の閲覧の
    トラフィックを下回る）。`GET /profile/me` `10→60`（SPA のすべての画面遷移／起動で発火する）。
    `GET /payment/status*`（all、order、ticket）`5→20`（PayPal の非同期のキャプチャのフロー（§7）の間にポーリング
    される — 購入手続きの途中で 429 になるのは、これが最も痛い場所である）。`GET /order/single_placed_order/{id}`
    `3→15`（単純な読み取りなのに、同じファイルでその上にある `checkout_order` の実際の変更と同じ予算になっていた —
    意図的というよりコピペに見えた）。`GET /notifications/unread-count` `30→60`（ポーリングされることが明示的に文書化
    されており、`notification.py` 自身のコメントがポーリングの頻度を「十分上回る」と言っている — 余裕を広げた）。
    `GET /shipping_addresses/fetch` `5→20`（購入手続きの住所の選択のステップで叩かれる）。

    **調整の問題ではない別のバグ**: `GET /shipping_addresses/fetch_byid/{address_id}` は `ip_key` をキーにしており、
    `user_key` を使っていない唯一の配送のエンドポイントだった — 同じ IP の背後にいる全員が、任意のユーザーの ID に
    よる住所の取得について 1 つのバケットを共有し、ネットワークを切り替えたユーザーは自分のものをリセットできた。
    このリソースの兄弟のすべてのエンドポイントに合わせて `user_key` に修正した。間違っていたのはキーだけで数値では
    なかったので、上限は `5/60` のままにした。**これでルートが壊れた**: 兄弟と違い、これには `get_current_user` の依存性が
    ないので、`user_key` はユーザーを見つけられず、すべてのリクエストが 500 になる — `docs/bugs_JP.md` #28 として
    未解決。

    **ベンチマーク中に見つけ、ここで修正した隙間**: `GET /products/{id}/detail`、`GET /groups/{id}/detail`、
    `GET /idols/{id}/detail` には、同じパターン（項目 31/33 の ID ごとの詳細のキャッシュ）のキャッシュが裏にある兄弟の
    読み取り（`/products/all`、`/products/store-page`、`/groups/all`、`/idols/all`、すべて `10-30/60, ip_key`）と違い、
    `rate_limit` の依存性がまったくなかった。3 つすべてに `rate_limit(30, 60, ip_key)` を追加し、
    `/products/all`/`/products/store-page` ですでに使っている予算に合わせた — ID ごとの詳細ページは少なくとも一覧ページと
    同じくらい閲覧されるので、ここでより厳しい数値にする理由はない。

    **`GET /concerts/{id}/detail`** にも同じリミッターの欠如があったが、他の 3 つが得た一律の `ip_key` をそのまま使う
    ことはできなかった: これは認証が任意（`get_current_user_optional`）で、トークンが実際に提示されたときにだけ
    `request.state.user` を設定する（`app/deps/auth.py`）— 素の `user_key` では、ゲストのすべてのリクエストで
    `AttributeError` を送出してしまう。`app/cache/rate_limit.py::user_or_ip_key`（`request.state.user` が設定されて
    いれば `user.id` をキーにし、そうでなければ `ip_key` のバケットにフォールバックする）を追加し、
    `rate_limit(30, 60, user_or_ip_key)` を組み込んだ。リミッターが `request.state.user` を設定される前ではなく、実際に
    設定された後に読むよう、シグネチャの中で `current_user` の `Depends(get_current_user_optional)` の後に置いた。

    マネージャー／管理者の CRUD（キャンペーン／アルバム／券種／ジャンル／グッズで一律 `20/60`）と、管理者に関わる
    機微な操作（`make-admin`/`create-manager`、`3/60`）は見直したうえでそのままにした — 認証済みで特権的であり、
    通常の利用で摩擦になるところではない。
46. **`GET /products/store-page` のベンチマークで、同時実行時のレイテンシーについての疑問が浮上した。まだ解決して
    いない。** 新しい `30/60` の制限に対するローカルでの 2 回の実行: 同時実行数 1（15 秒）では p50/p90/p99/max が
    76/88/111/680ms、同時実行数 3（20 秒）では 133/220/1735/1853ms — テールは同時実行数とともに急激に伸びるのに、
    スループットはほとんど伸びない（約 9.7 → 約 11.6 req/s で、3 倍にはほど遠い）。`app/router` にわたる 161 個
    （現在は 163 個）のルートハンドラーのどれもが `async def` ではなく素の `def` であることを `grep` で確認した（ツリーの
    中で唯一の `async def` である `payment.py::_raw_body` は、ルートハンドラーではなく、Webhook の生のボディを読むための
    非同期の依存性である）— `architecture_JP.md` §2 と正確に一致しており、そこにドキュメントのずれはない。

    最初の仮説（スレッドプール／DB のコネクションプールの競合）は成り立たない: `app/db/session.py` は、約 40 スレッドの
    FastAPI のスレッドプールに対して、少数の接続で多くの同時リクエストをさばけるよう、プールを 10 接続
    （`pool_size=5, max_overflow=5`）にしている — 3 つの同時リクエストはどちらの上限にもほど遠く、§2 で `async def` を
    やめた目的そのものが、リクエストを列に並ばせるのではなく本当に並行して実行させることだった。より裏付けがあるが
    まだ確認されていない仮説: CPython の GIL — ブロッキングな Redis/Postgres の I/O は待っている間それを解放するが、
    その周りの CPU を使う処理（Pydantic の検証、msgpack のパック／アンパック、JSON のエンコード）は解放しないので、
    並行するスレッドには、逐次的な単一の呼び出し元では決して起きない GIL の受け渡しの遅延が見えうる。既存のコールド
    キャッシュのミスの仮説（キャッシュヒットのレスポンスの中に 1 回の本当の Postgres の往復がある）は別物で、これも
    まだ確認されていない。どちらも切り分けられていない: `benchmark/bench.py` の `Results` は現在、`200`/`429` の
    レイテンシーを 1 組のパーセンタイルに混ぜており、どのリクエストが実際に遅かったのかが見えない。次のステップで、
    まだやっていないもの: より確かな結論を出す前に、レイテンシーの追跡をステータスコードで分ける（または CSV の出力に
    リクエストごとのタイムスタンプを加える）— これが確定した知見として誤って引用されないよう明記しておく。

    **更新 — ステータスごとの分割を作って実行した**（`bench.py` は今、ステータスコードごとのパーセンタイルを報告し、
    `timestamp,status,latency_ms` の行を書き出す）。知見、Windows 上のローカルの Docker Compose:
    - **下限**: `429`（Redis の `INCR`+`TTL` を 1 回、DB なし）は同時実行数 1 で p50 約 88ms かかる。Redis は Compose の
      ネットワーク上にあるので、これはキャッシュのコストではなく環境のオーバーヘッド（Docker Desktop のポート
      フォワーディング、単一の `uvicorn --reload` のプロセス）である。すべてのリクエストに当てはまり、Render には
      持ち越されない。
    - **温まったキャッシュヒットのコスト**: 同時実行数 1 で `200` の p50 102.6ms に対して `429` の p50 87.6ms なので、
      Redis の `GET` + msgpack のアンパック + `StorePageRead` の検証 + レスポンスのエンコードで約 15ms 加わる。
    - **同時実行数 3 では**、`200` は `429` よりはるかに劣化する（p50 で ×3.2 対 ×1.4）。方向は GIL の仮説に合う（`200`
      の経路のほうが CPU の処理が多い）が、約 15ms の追加の処理だけでは、約 230ms の追加のレイテンシーは説明できない。
    - **分割によって露わになった交絡**: IP ごとに `30/60` の予算だと、すべての `200` は実行の最初の数秒に入り、すべての
      `429` はその後に入るので、この比較はウォームアップと定常状態の比較でもある。同時実行数 3 では、30 件の `200` の
      うちちょうど 3 件が 688ms の p90 を上回っており、これは **キャッシュスタンピード** に合う:
      `CacheService.get_cached_store_page` には再構築のロックがないので、N 件の同時のミスがすべて
      `ProductService.get_store_page` を実行し、すべてが同じキーを `setex` する。N=3 なら無害だが、実際のトラフィック
      では `TTL_SECONDS`（5 分）の期限切れのたびに繰り返される。コールドな実行（先に `products:store_page` を削除し、
      同時実行数 3）で **確認した**: 最も遅い 3 件の `200` はリクエスト #1〜3 で、互いに 53ms 以内に開始し、それぞれ
      約 1.0〜1.1 秒かかった。3 つとも、どれかが終わる前に開始していたので、3 つとも必然的にキャッシュをミスして
      再構築した。
    - **スタンピードが説明するのはテールだけで、中央値ではない。** キャッシュが温まった後（リクエスト #4〜30）も、
      `200` は同時実行数 1 での約 100ms に対して、同時実行数 3 では約 300〜500ms かかった。同時実行数 3 倍でおよそ
      3 倍である。スループットが同時実行数とともにほとんど伸びないこととあわせると、どこかでリクエストがほぼ 1 件
      ずつ処理されているように見える。それがどこかはまだ未解決: ローカルの環境（Windows 上の Docker Desktop の
      ネットワーク、`--reload`）と GIL の下での CPU の処理のどちらも候補である。Docker の外で `--reload` なしでアプリを
      実行すれば、それらを切り分けられる。
    - **説明できていないこと**: 実行がカバーする時間が `--duration` より短い。コールドな同時実行数 3 の実行の
      リクエストは、20 秒の期間のうち 12.7 秒にわたっており、その範囲の中に計測されていない隙間はない（各ワーカーの
      レイテンシーの合計 ≈ 12.65 秒）。そのため、欠けている約 7 秒は最初のリクエストの前か、最後のリクエストの後に
      ある。以前の同時実行数 1 の実行でも同じことが見られた（15 秒で 34 リクエスト、計測されたのは約 3.5 秒）。

47. ~~**ログインしている任意のユーザーが、任意の配送先住所を更新・削除できた**~~ — **修正済み**。
    `ShippingService.update_address`/`delete_address` は `ShippingAddress.user_id==user_id` ではなく
    `user_id==user_id` — Python の引数を自分自身と比較するもので、常に `True` — でフィルタしていたので、本当のフィルタは
    住所の ID だけだった。実際の HTTP で確認した: 2 人目のファンが 1 人目のファンの住所に対して行った `PUT` と `DELETE`
    は、どちらも `200` を返した。モックの `Session` を使ったユニットテストではこれを捕まえられなかった: `MagicMock` の
    `.filter()` はどんな条件でも受け付ける。これとは別に、`GET /shipping_addresses/fetch_byid/{address_id}` には認証の
    依存性がまったくなく、すべての呼び出し元に `500` を返していた（その `user_key` のレートリミッターは、
    `get_current_user` だけが設定する `request.state.user` を読む）。そのクエリも所有者でフィルタしていなかったので、
    500 だけを直していたら、ID によってすべての住所が露出するところだった。今は認証を必須とし、所有者でフィルタする —
    他人の ID は `404`。`docs/api-spec_JP.md` を更新した（🔓 → 🔒）。リグレッションテスト:
    `tests/integration/marketplace/test_shipping_addresses.py` — 10 件のテストのうち 5 件が古いコードに対して失敗する。

48. ~~**マネージャー／管理者の設定ページの読み取りに、認証もサーバー側の事務所スコープもなかった**~~ — **修正済み**
    （`docs/bugs_JP.md` #29）。`GET /products/manager-products-page`、`/products/manager-product-form-page`、
    `/idols/manager-idols-page`、`/idols/manager-idol-form-page`、`/groups/manager-groups-page`、
    `/concerts/manager-events-page` は匿名で呼び出せ（HTTP で確認: トークンなしの呼び出し元に、無効化されたアイドルと
    一覧に載っていない商品が返ってきた）、2 つの商品ページはクエリ文字列から任意の `company_id` を受け取っていた。
    6 つすべてが今、`GET /order/manager-orders-page` に合わせて、`require_manager_or_admin` と
    `rate_limit(30, 60, user_key)`（マネージャー／管理者のティア、`architecture_JP.md` §3）を必須にしている。
    マネージャーは自分の事務所の行だけを受け取る:
    - 商品ページは `company_id` をマネージャーの事務所に固定する（管理者は引き続き指定でき、省略すればすべての商品を
      得る）— これらのキャッシュはすでに事務所ごとのキーだった。
    - アイドル、グループ、イベントのページは全事務所の Redis のエントリを 1 つのまま保ち、ルーターが各サービスの純粋な
      `scope_manager_*` ヘルパーを通じてリクエストごとにそれをフィルタするので、キャッシュのキーと書き込み側の
      無効化は変わらない。商品フォームのページのアイドル／グループの選択肢も同じ方法でフィルタされる。
    会場、メンバーカラー、カテゴリは事務所間で共有されており、フィルタされないまま。フロントエンドへの影響（すべての
    呼び出しでトークンを送らなければならない。クライアント側の事務所のフィルタリングは削除できる）:
    `docs/frontend-tasks/manager-pages-and-address-auth_JP.md`。テスト:
    `test_permissions.py::test_manager_settings_page_role_gate`（7 つすべてのマネージャーページについて 401/403/200）、
    加えて `test_idol_group_management.py`、`test_product_management.py`、`test_ticket_and_concert_endpoints.py` の
    マネージャーと管理者のスコープのテスト。

## 5. 意図的に延期したもの — 次のフェーズで、忘れてはいない

- ~~**グループ／アイドルの CRUD の成功の経路の結合テストのカバレッジ**~~ — **完了**:
  `tests/integration/talent/test_idol_group_management.py` が、所有者のマネージャーと管理者による実際の HTTP での作成／
  更新／論理削除／再有効化／画像のアップロード、事務所をまたぐ 403、参照の検証（他の事務所のグループ、無効化された
  グループ、未知のカラー）をカバーしている。
- **`/payment/status/order/{id}` の見つかった場合** — 401/404 の経路だけが結合テストされている（項目 34）。本当の
  見つかった場合には、実際の `/order/checkout` の呼び出しの裏に、商品／カテゴリ／配送先住所の完全なチェーンが必要で、
  まだ作っていない。対応するチケット側のエンドポイント（`/payment/status/ticket/{id}`）は完全にカバーされている。
  本物のチケットは用意するのが安い（公演／会場／券種／キャンペーンで、再利用できる `Factory` の形がすでにあった）
  からである。
- ~~**購入の並行性／ロックの経路のユニットテスト**~~ — **一部完了**。ユニットテストではなく、稼働中の Postgres に
  対する本物の結合テストとして。これはこの種類のバグにとってより強い証明の形である（§4 の項目 1 のリグレッションの
  記述を参照 — そのバグは目視では見えず、本当の並行トランザクションの下でしか表面化しなかった）。
  `order_service.checkout` と `lottery_draw_service.draw_lottery`（項目 8）は今カバーされている —
  `tests/integration/marketplace/test_orders_concurrency.py`、`tests/integration/events/test_lottery_concurrency.py`、
  そして `tests/integration/events/test_ticket_checkout_concurrency.py` の `ticket_service.checkout_ticket`（最後の席は
  一度だけ売れる、二重送信、1 つの公演の 2 つのティアを同時に、同じ冪等性キーを 2 回）と、
  `tests/integration/events/test_won_ticket_checkout.py` の `ticket_service.checkout_won_ticket`（支払いを二重送信した
  当選者は一度だけ支払う、同じ冪等性キーを 2 回、期限後の並行した試行でも席はちょうど一度だけ解放される）。
- **支払いの失敗の処理** — モックゲートウェイの拒否の経路（`simulate_succ=false`）はずっと動いている。PayPal の拒否の
  経路（`finalize_paypal_payment` の `else` の分岐、§7）は実装されているが、本物の拒否されたサンドボックスの決済に
  対してはまだ試していない。
- ~~**一般販売／「予約」（抽選なし）の購入フロー**~~ — **完了**: `TicketService.checkout_ticket`
  （`POST /tickets/checkout`）が本当の一般販売の購入経路である — `ticket_types.sale_method == 'direct'`、open な
  `DirectSaleCampaign` の期間、残りの在庫、そして抽選の経路が使うのと同じ「1 公演に有効なチケット 1 枚」／「未解決の
  抽選の状況」のゲートをチェックし、`checkout_won_ticket` と同じ方法でロックして支払う。`add_ticket`（管理者専用の
  手動発行、`POST /tickets/add`）は別の暫定措置のまま。抽選は自分でチケットを挿入し、それを通らない。
- ~~**抽選ジョブの実際の実行方式**~~ — **完了**: Celery Beat のスケジュールではなく、マネージャーが実行する。実行の
  エンドポイントが、抽選を実行する Celery タスクをキューに入れる（§8）。
- **支払われなかった抽選当選チケットの失効を掃除するジョブがない** — `database-design_JP.md` §5.2 のシーケンス図で
  設計されているが、作っていない。今日これが遅延的にでも発見される唯一の場所
  （`PaymentService.finalize_paypal_payment`）は、そこへの狭い経路の 1 つしかカバーしない。新しい購入／抽選の並行性の
  テストで明示的にスコープ外にしている理由を含む全体の記述: §8 の「既知の制限事項」の注記。
- 「そのティアにまだ順位を付けていないので、この抽選には応募できません」に対する **UI のメッセージ** — 応募は
  サーバー側で正しく拒否されるが、クライアント向けの促しは設計されていない。
- **`idols.real_name`** — 意図的にモデル化していない。
- **ETL／データパイプライン** — アーキテクチャと並ぶ、プロジェクトの概要のもう 1 つの主要な目標で、未着手。自然な
  発生源のイベント（チケットの購入、抽選の応募 + 抽選結果、決済の Webhook、発送ステータスの変化）は、将来のジョブが
  OLTP のテーブルをかき集めたり `updated_at` をポーリングしたりするのではなく、ビジネスの書き込みと同じ
  トランザクションで書き込まれるアウトボックス／イベントのテーブル（`domain_events`: type、payload、occurred_at、
  処理済みフラグ）に送るのがおそらくよい。下流の形の候補: 分析に向いたファクトテーブル（`fact_sales_by_concert`、
  `fact_lottery_conversion`、`fact_fan_activity`）への定期的な変換で、同じ Postgres インスタンスの別のスキーマか、
  スコープが広がれば本物のデータウェアハウスに置く。OLTP の形がさらに固まる前にファクトテーブルを設計しないこと —
  `lottery_entries.source_order_item_id` が削除された（`database-design_JP.md` §3.13）ことで、抽選の応募はもう購入の
  文脈を持たず、これは作った後ではなく作る前に解決する価値がある。
- **商品の「パーソナリティ」** — 概要の 3 つ目の目標（文言の語り口、アイドル／ファンダム特有の味付け、`/docs` の
  ブランディング、エラーメッセージ、メールのテンプレート）。`idol_colors` のパステルのパレットはその種の 1 つで、
  もう 1 つは FAQ アシスタントの語り口（「明るく、遊び心があってかわいらしく」、事実は正確に述べる）で、開発者が
  `faq_answer_service.SYSTEM_PROMPT` で選んだ。それ以外は何も設計されていない。推測で細部を作り出さないこと —
  次の計画の話し合いで挙げること。
- **`schema.sql`** — `database-design_JP.md` 全体で存在するかのように引用されているが、存在しない（上の §1）。稼働中の
  マイグレーション／モデルから生成するか、引用をやめて、マイグレーション自体を参照用の DDL として扱うこと。
- **すべての商品は所有者を持たなければならない（`album_details` または `merch_details` の行を持つ）— 提案済みだが
  未設計。** 今日、所有者のない商品は完全に正当な状態である（`database-design_JP.md` §3.15/§6）— それを強制したり
  挙げたりするものは何もなく、それが項目 14 のバグを存在させた。所有者を *必須* にするのはバグ修正ではなくポリシーの
  変更であり、商品の作成が意図的に 2 段階（まず素の `Product`、その後に所有者の行）であることと衝突する — 作成時に
  それを強制するには、アトミックな作成フローか、コミット時にチェックされる `DEFERRABLE` 制約のどちらかが必要になる。
  より穏やかな代替案: `products.status`（`draft`/`published`）によるゲート、または DB レベルの強制なしの定期的な監査
  クエリ。これもまだ決まっていない: これはすべての商品に適用されるのか、それとも一部のグッズは意図的に所有者なしの
  ままにすべきか？

## 6. 推奨する次のステップ（順番に）

1. ~~稼働中の Postgres/Redis に対する本物の `alembic upgrade head` + エンドポイントのスモークテスト~~ — **完了**:
   Render + Supabase にデプロイ済みで、CI が Postgres に対してマイグレーション + スイート全体を実行する（§3）。
2. ~~抽選ジョブや一般販売の購入フローをその上に作る前に、購入／チケットの在庫の競合を修正する~~ — **完了**。§4 の
   項目 1 を参照。
3. ~~並行性のガードを最初から設計に組み込んで、抽選ジョブ（§5/§8）を作る~~ — **完了**。§8 を参照。
4. ~~サービス層で欠けていた *主要な* ファンのみ購入可能のチェックを埋める~~ — **修正済み**。
   `cart_service.add_to_cart`、`order_service.checkout`、`ticket_service.checkout_ticket` はそれぞれ、他のことをする前に
   購入者の `role == "fan"` をチェックし、`FanOnlyPurchaseError`（既存の DB トリガーの保険の例外で、新しいものを追加
   するのではなく再利用した）を送出する。`lottery_entry_service.apply_to_lottery`/`apply_to_lotteries` は同じチェックを
   行うが `ForbiddenError` を送出し、`ticket_service.add_ticket`（管理者の手動発行）は *受取人* がファンであることを
   チェックして `ForbiddenError` を送出する。

## 7. PayPal ゲートウェイの統合 — 実装済み、一部検証済み

**モックゲートウェイの設計が解決していなかった中心的な問題**: モックゲートウェイは `simulate_succ` フラグで成功／
失敗を同期的に決着させる。PayPal はそのようには動けない — 非同期の 3 段階の受け渡し（注文の作成 → 購入者の承認 →
サーバーによるキャプチャ）に加えて、キャプチャの呼び出しの前に、後に、あるいはその代わりに、ときには複数回届く
Webhook がある。在庫／キャパシティを減らすのを、決済が実際に確定した後の `finalize_paypal_payment` の中だけにし、
キャプチャのエンドポイントと Webhook を、重複したロジックではなく、その 1 つの共有の関数への 2 つの入り口にすることで
解決した。すでに決着した決済に対してそれを再実行しても何も起きない（`payment.status != PaymentStatus.pending` の
ガード）— そのステータスのチェックが冪等性の仕組みであり、別のイベント ID のテーブルではない。

**出荷したもの**:
1. `app/config/settings.py`: `PAYPAL_CLIENT_ID`/`SECRET`、`PAYPAL_MODE`、`PAYPAL_WEBHOOK_ID`。`httpx` 以外に新しい
   依存関係はない。
2. `app/utils/paypal_client.py`: `get_access_token()`（OAuth2 のクライアントクレデンシャル、プロセス内でキャッシュ）、
   `create_order()`、`capture_order()`、`verify_webhook_signature()`（証明書チェーンの検証を実装し直すのではなく、
   PayPal 自身の verify-webhook-signature エンドポイントに送り返す）、`extract_approval_url()`。
3. マイグレーションで `payment_gateway_enum` に `'paypal'` を、`payment.pg_approval_url` を追加する。
4. スキーマの `PaymentGateway.paypal` と `PaymentResponse.pg_approval_url`。
5. `order_service.checkout()`/`ticket_service.checkout_ticket()` の `paypal` の分岐は、Order/Ticket の行を pending で
   作成し、`create_order()` を呼び、`pg_order_id`/`pg_approval_url` を保存する — まだ在庫は減らさない。
   `finalize_paypal_payment` は関係する行をロックし直し（`with_for_update()`）、`capture_order()`（取り消せない外部の
   副作用 — 後でチェックすると、結果的に処理できない注文について PayPal が購入者のお金を取ってしまいうる）を呼ぶ
   *前に* 在庫／キャパシティをチェックして減らし、その後すべてを成功にして一度だけコミットする。2 つの
   エンドポイント: `POST /payment/paypal/capture/{pg_order_id}`（速い経路、認証あり）と `POST /payment/paypal/webhook`
   （突き合わせ、署名で検証、認証なし）。フロントエンドは完全に作られている: `PaypalReturnPage.vue` がクエリ文字列から
   トークンを読み、キャプチャのエンドポイントを呼び、本物の確認の UI を表示する。`PaypalCancelPage.vue` がキャンセルの
   リダイレクトを扱う。フロントエンド向けの流れの全体は `docs/api-spec_JP.md` §6 を参照。

**元の計画からの逸脱**: 予定していた `processed_webhook_events` テーブル（PayPal のイベント ID をキーにした冪等性）は
取りやめた — `payment.status != pending` のガードがすでに、どの呼び出し元が先に到達しても、Webhook が何回再配信
されても、維持すべき 2 つ目のテーブルなしに `finalize_paypal_payment` を冪等にしている。

**検証済み**: 本物の PayPal Sandbox でのチケットの購入をエンドツーエンドで（注文の作成 → 承認 → キャプチャ →
`Payment`/`Ticket` が success/paid に変わる）、ローカルとデプロイ済みの Render アプリの両方で確認した（そのため、
`PAYPAL_MODE`/`FRONTEND_BASE_URL`/CORS もそこで正しく組み込まれている）。
~~注文のフロー（マーケットプレイス）の購入は、本物の PayPal に対してエンドツーエンドで実行していない~~ — **完了**:
チケットのフローと同じ方法で、本物の PayPal Sandbox に対して、同じ注文の作成 → 承認 → キャプチャ →
`Payment`/`Order` の成功の流れで実行した。

**まだ検証していない — 既知の制限事項**:
- Webhook の経路は本物の配信もシミュレートされた配信も一度も受け取ったことがない — 本物の ngrok のトンネルでも
  PayPal 自身のシミュレーターでも、受信したリクエストはゼロで、これはハンドラーの確認されたバグというより、
  トンネルとしてフラグの付いたドメインへの配信を PayPal が黙って落とすという既知のパターンと一致する。ハンドラーの
  コードが悪いと判断する前に、ngrok の代わりに `cloudflared` を試すこと。
- 拒否の経路（`finalize_paypal_payment` の `else` の分岐）はコードレビューはしたが、本物の拒否されたサンドボックスの
  決済に対しては試していない。
- 放置された PayPal の購入手続きを掃除する処理がない — 承認もキャンセルもされなかった `pending` の注文／チケットは
  いつまでも `pending` のまま残る。在庫が誤って確保されることはない（一度も減らされていない）が、行は残り続ける。
  これに失効のジョブが必要かどうかはまだ未解決。
- `finalize_paypal_payment` が、同じ注文についてキャプチャのエンドポイントと Webhook の両方から同時に呼び出される
  ことに対してロックを必要とするかどうか: `with_for_update()` のロックと pending のステータスのガードが実際には
  これを塞いでいるように見えるが、競合のテストはしていない。

## 8. マネージャーが実行する抽選ジョブ — 実装済み

`PUT /concerts/lottery-draw/{id}`（`app/router/events/concert.py`）は `app.tasks.lottery.draw_lottery`
（`app/tasks/lottery.py`、`celery_app` の `include` のリストに登録済み）をキューに入れ、それが
`LotteryDrawService.draw_lottery`（`app/services/events/lottery_draw_service.py`）を呼ぶ。

**実行方式: 事務所のマネージャー（または管理者）が HTTP の操作で抽選を実行する**。自分の事務所の公演にスコープ
される — `lottery_campaigns.draw_at` に対する Celery Beat の cron ではない。これはプロジェクトの他の部分が使っている
のと同じ RBAC／事務所スコープの話を広げるものであり、在庫を確保するものについて、無人の予定されたジョブではなく、
責任を持つ人間の操作を与える。`draw_at` はファン向けの予定時刻としてスキーマに残る — それが抽選が実際に実行される
瞬間である必要はない。

**実行のエンドポイントは、アルゴリズムをインラインで実行するのではなく Celery タスクをキューに入れる** — 抽選は
公演のすべてのキャンペーン／応募／希望／券種の行に触れるので、リクエスト／レスポンスのサイクルには収まらない。
ルーターは同期的で小さいままにする: 公演が存在することとマネージャーの事務所スコープをチェックし、
`lottery_draw_triggered` 通知を送り、タスクを送り出し、「scheduled」のメッセージとともに `200` を返す。「受付が終了した
open なキャンペーンがあるか」のチェックはタスクの中で実行されるので、その失敗は HTTP のエラーではなく
`lottery_draw_failed` として表に出る。タスクは（FastAPI のリクエストスコープの `get_db` ではなく）
`app.db.session.session()` で自分の DB セッションを開き、抽選のアルゴリズムを直接呼ぶ。実行の粒度はキャンペーン
ごとではなく公演ごとである — `database-design_JP.md` §5.2 の順位の繰り下げには、1 つの公演のすべてのティアの
キャンペーンをまとめて抽選する必要があり、そうでないとファンの「1 公演に最大 1 枚」の保証が壊れる。

**RBAC**: 公演は `company_id` を直接持つので、`concert_service`/`ticket_type_service` が使うのと同じ 1 段階の
`_manager_scope_violation(current_user, concert.company_id)` のチェック。

**並行性のガード**: 公演の対象となるすべての `ticket_types` の行、その下の `lottery_campaigns` の行、それらの
`pending` の `lottery_entries` に対する `with_for_update()`。明示的なロックの順序はない — 今日安全なのは、1 回の抽選の
すべてのロックがその 1 つの公演自身の行にスコープされているからにすぎず、2 つの同時の抽選がデッドロックする形で
部分的に重なることはない。そのスコープの前提が変わることがあれば、明示的な順序を付ける価値がある。対象になるのは
`status='open'` のキャンペーンだけなので、エンドポイントは自己冪等になる — ダブルクリックや 2 人のマネージャーの
間の競合では、2 回目の呼び出しは open なものを何も見つけない。

**アルゴリズム**（`database-design_JP.md` §5.2 のシーケンス図に対応）: 対象のキャンペーンのいずれかで受付が終了して
いなければ拒否する。次に `rank = 1, 2, 3, ...` について、今回の実行でこの公演の他のティアでまだ当選していない
ユーザーがこの順位を付けた、すべてのティアの `pending` の応募を集め、各ティアの残りのキャパシティまで当選者を
サンプリングし、それらを `won` にして `Ticket(status='pending_payment')` を挿入し `sold_quantity` を増やす。最後の
順位の後、まだ `pending` のすべての応募は `lost` になる。処理したキャンペーンを `drawn` にする。最後に一度だけ
コミットする。

**乱数**: デフォルトの `random` モジュールや `ORDER BY random()` ではなく、`secrets.SystemRandom().sample(candidates,
k)`。ビジネスルール（購入による倍率なし、すべてのファンがちょうど 1 回のチャンスを得る）がすでに方法を一様な
サンプリングに決めている — 正しくする価値があるのはその源である: `random` の Mersenne-Twister の PRNG は統計的には
一様だが暗号学的に安全ではなく、`secrets.SystemRandom()` は OS の CSPRNG に裏付けられ、そのまま置き換えられる。
順位やティアをまたいだ除外の管理は本質的に手続き的なので、サンプリングは SQL ではなく Python で実行する。

**通知**: `draw_lottery` は `lottery_result`（すべての当選者と落選者）と、当選者だけには
`lottery_payment_reminder`（抽選時に一度だけ発火し、後のスケジュールではない）を、抽選自体と同じトランザクションの
中で書き込む — 同じデータベースへの安い挿入なので、抽選のコミットに結びつけても何のコストもかからず、アトミック性が
得られる。当落は **アプリ内通知だけで、メールはない**: `draw_lottery` は以前、応募ごとに `celery_app.send_task` で
`LOTTERY_WON`/`LOTTERY_LOST` のメールも送っていたが、シードのファンの実際のメールアドレス（ローカル開発の早期
リターンではなく Resend）に対して抽選のフローをテストしても、抽選のたびに本物の受信箱に大量のメールが届かない
ように削除した。テンプレート自体も、組み込みを外しただけでなく `EmailTemplate` から削除した。当選したチケットが
実際に支払われたとき（`PaymentService.finalize_paypal_payment`）の `lottery_payment_confirmation` については引き続き
メールが発火する — 決済の成功とチケットの確定はメールに値するイベントのままで、抽選ごとの当落はそうではない。
再現可能／監査可能な抽選（順位ごとにシード + 候補のスナップショットをログに出す）も検討したが、意図的に作らなかった
— このプロジェクトのスコープの中に、異議申し立てのプロセスをモデル化するものは何もない。

別の `lottery_draw_triggered` 通知は、より早く、このトランザクションの完全に外で発火する — ルーターから、
マネージャー／管理者が抽選を押した瞬間に（`ConcertService.notify_managers_of_draw_trigger`、§2 の通知の項目）、上の
Celery タスクが実行されるより前に。それは事務所のすべてのマネージャーに、抽選が今進行中であることを伝える。

その後タスク自体が送出した場合 — 受付がまだ終わっていないというチェック、ダブルクリックによる終了済みキャンペーンの
競合、本当のバグ — `draw_lottery_task`（`app/tasks/lottery.py`）がそれを捕捉し、ロールバックし、公演を検索し直し
（`draw_lottery` の中のローカルな `Concert` オブジェクトは送出した時点でなくなっている）、同じ対象への
`lottery_draw_failed` 通知のために `ConcertService.notify_managers_of_draw_failure` を呼び、その後元の例外をそのまま
再送出する — そのため、失敗の通知と Celery 自身の `FAILURE` のタスクの状態は両方とも起き、どちらかがもう一方を
置き換えることはない。正常な経路では、`draw_lottery` は今、自身のコミットの直後に
`ConcertService.notify_managers_of_draw_completion`（`lottery_draw_completed`）も呼ぶ — そのため、抽選が終わったときに
公演の編集ページを見ていなかったマネージャーも、抽選が始まったことや失敗したことだけでなく、実際に完了したという
永続的な記録を持てる。3 つのマネージャー向けの通知（`lottery_draw_triggered`/`lottery_draw_failed`/
`lottery_draw_completed`）はすべて `concert_id` だけを持ち — 当選者ごとの詳細は持たない — 実際の結果は
`GET /lottery_entries/concert/{concert_id}/results`（`api-spec_JP.md` の Lottery Entries）で、決着したすべての応募を、
当選者のメールアドレスとそのチケットの支払い状況／期限とともに返すマネージャー向けのエンドポイントである。

`draw_lottery_task` の Celery の戻り値も、生の `LotteryResult` ではなく `.model_dump(mode="json")` でシリアライズして
いる — そのモデルは JSON でシリアライズできなかったので、抽選自体はすでに正常にコミットされていたのに、Celery の
kombu のエンコーダーが送出してタスクを `FAILURE` として記録していた。本物のワーカーのログから捕まえ、タスクを直接
呼んでその戻り値を `kombu.utils.json.dumps` でエンコードすることで再現し、修正し、同じ方法で再検証した。これとは
別に、`LotteryEntry.drawn_at` — `LotteryEntryRead` で公開され、上の結果のエンドポイントで使われる本物のカラム — は、
実際には `draw_lottery` によって一度も設定されていなかった（`LotteryCampaign.draw_at` だけが設定されていた）。
そのエンドポイントを作っているときに見つけ、各ステータスの変更とあわせて `entry.drawn_at`/`candidate.drawn_at` を
設定することで修正した。

**配置**: `lottery_campaign_service.py` に組み込むのではなく、`app/services/events/lottery_draw_service.py`。抽選は、
素のキャンペーンの CRUD とは意味のある形で異なる関心事（`LotteryCampaign`/`LotteryEntry`/`LotteryPreference`/
`TicketType`/`Ticket` に触れる）である。

**未解決の問い**: エンドポイントは受付が終了していることだけをゲートにすべきか（マネージャーがタイミングについて
完全な裁量を持つ）、それとも `now() >= draw_at` も必須にすべきか（実行が完全な裁量ではなく「確認」になる）？ 前者に
傾いている。スキーマの話の中で `draw_at` が意味するものが変わるので、ここで推測で決めてはいない。

**検証**: 実装済みで、ユニット／結合テスト済み。特に並行性のガード（上で述べた `with_for_update()` のロック）は今、
本物の稼働中の Postgres に対して確認されている — `tests/integration/events/test_lottery_concurrency.py` は同じ公演に
対して 2 つの同時の `draw_lottery` の呼び出しを競合させ、ちょうど 1 つが勝ち、負けたほうは open なキャンペーンが
残っていないことを正しく見つけ、`sold_quantity`／チケット／当選した応募の数が一貫したままであることを確認する
（§4 の項目 1 のリグレッションの記述に全体の文脈がある — その同じテストを書く取り組みが、購入の別の場所で本当の
売り越しのバグを捕まえた）。まだ未解決: 多数のファンによる完全な抽選（その競合テストが投入するティアごと 3 人の
候補より多い）は、稼働中の Postgres に対して試していない。

**既知の制限事項 — 支払われなかったチケットの失効を掃除するジョブがない**（`database-design_JP.md` §5.2 の
シーケンス図の「支払われなかったチケットの失効を掃除するジョブ」）: 抽選に当選したのに `tickets.payment_deadline_at`
までに支払わなかったファンの枠は、永久に確保されたままにならないよう解放されるべきである
（`tickets.status='expired'`、`ticket_types.sold_quantity -= 1`、任意で落選者の中から再抽選）。今日これがチェック
される唯一の場所は `PaymentService.finalize_paypal_payment` の遅延的な発見（そのコメント自身が「no sweep job exists
yet ... so this is the one place that does it」と言っている）で — それは、誰かがたまたまそのチケットについてその
特定の PayPal の確定の経路を叩いたときにしか発火しない。他に `payment_deadline_at` を読むものは何もない。作って
おらず、どこにも予定されていない — §5 の延期のリストを参照。**項目 1 の修正とあわせて追加した並行性のテストからは
除外している**（`test_orders_concurrency.py`、`test_lottery_concurrency.py`）: それらは `order_service.checkout` と
`draw_lottery` という、どちらも本物のコードの経路を競合させる — まだ存在しない掃除のジョブには、競合させるものが
何もない。
