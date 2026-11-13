# バグ／コードスメル — 監査バックログ

[English](bugs.md) | 日本語

認証、購入／決済、チケット、抽選、キャッシュ、ストレージのコードを静的に読み通した結果（2026-09-24）です。
**稼働中のアプリやテスト実行で再現したものではありません** — 各項目は実行時に観測したものではなく、コード上で
追跡したものです。修正したら項目にチェックを付けてください（または `project_status_JP.md` §4 に移してください）。

未解決の項目はすべて 2026-11-13 にコードと照らして読み直しました（今回も静的な確認で、実行はしていません）。
いずれも現在も当てはまります。この見直しで行番号の参照を直し、以下の **レビュー** の注記と #30〜#32 を追加しました。

## 🔴 致命的

- [x] **1. 注文ごとに `shipping_status` 行が重複する** — 修正済み（`project_status_JP.md` §4 の項目 43 を参照。
  マイグレーション `a9d3f5b7c1e2`、その後結合テストスイートと CI で Postgres に対して適用済み）。`OrderService.checkout`
  （`order_service.py:98`）が 1 行挿入するようになったが、`PaymentService.create_payment`（`payment_service.py:54`）が
  すでに挿入しており、`finalize_paypal_payment`（210 行目）がさらにもう 1 行追加する。`UNIQUE(order_id)` がなく、
  `Order.shippingstatus` は `uselist=False` なので、どの行が読み込まれるかは不定 — 決済が拒否された注文が `pending` と
  して読まれ、発送されてしまうことがある。`project_status_JP.md` の項目 43 の前提（「shipping_status 行を挿入する処理が
  なかった」）は誤り。修正 + 一意制約を追加する。
- [ ] **2. 商品を削除すると注文履歴が削除される。** `order_items.product_id` は `ON DELETE CASCADE`
  （`models/marketplace/order.py:34`）で、`delete_product` はハードデリートする（`product_service.py:201`）。どの
  マネージャーでも、所有者のないグッズに対してこれを実行できる。項目 17 と同じ種類。
- [x] **3. カートの IDOR。** **修正済み**: クエリが `Cart.user_id` でもフィルタするようになった。
  `CartService.remove_cart`（`cart_service.py:51`）は `Cart.id` だけでフィルタしており、`user_id` は受け取るが使われて
  いない — どのユーザーでも他人のカートの行を削除できる。
- [x] **4. 抽選への応募が受付期間とキャンペーンのステータスを無視する。** `_stage_entry`
  （`lottery_entry_service.py:31`）は `entry_start_at`/`entry_end_at`/`status == open` をチェックせず、それをする
  トリガーもない。抽選後の応募は永久に `pending` のまま残り、`_unresolved_lottery_entry` を通じてその公演の一般販売での
  購入をブロックする。
  **サービスで修正済み**: `_stage_entry` はキャンペーンを `FOR SHARE` で読み込み、`status == open` かつ現在時刻が
  受付期間内でない限り応募を拒否する。共有ロックにより、応募と抽選の `FOR UPDATE` が直列化される。
  `tests/integration/events/test_lottery_apply_window.py` は実際の Postgres に対してこの 2 つを競合させる（ロックを
  外すと失敗する）。未解決の点: DB トリガーによる保険はなく、open でないキャンペーンで `pending` のまま止まっている
  既存の応募は一度きりのクリーンアップが必要。
- [x] **5. 希望の編集で公演の抽選が壊れる。** `set_preferences`/`clear_my_preferences` は pending の応募があっても
  動作し、その後抽選の `next(p for p in preferences ...)`（`lottery_draw_service.py:55`）が `StopIteration` を送出して
  全員分の抽選が中断される。受付終了後の順位の付け直しも許してしまう。
  **修正済み**: `set_preferences`/`clear_my_preferences` は `_check_ranking_change_allowed` を実行する。現在と新しい
  ティアのキャンペーンを `FOR SHARE` で読み込み、終了済み／抽選済みのキャンペーンがあれば変更を拒否する。新しく順位を
  付けるティアにはすべて、受付期間が始まっている open なキャンペーンが必要（ファンは既存のキャンペーンを通じて順位を
  付ける）。pending の応募があるティアの削除は拒否される。
  `tests/integration/events/test_lottery_preference_guard.py` が実際の Postgres に対してこれをカバーしており、抽選の
  ロックとの競合も含む（ロックを外すと失敗する）。
- [x] **6. 同じファンが 1 つのティアで 2 回当選しうる。** `max_entries_per_user > 1` の場合、
  `sample(candidates, ...)` が同じユーザーの 2 つの応募を選ぶことがあり（`won_user_ids` は候補を組み立てるときにしか
  チェックされない）、`trg_tickets_one_per_concert` がコミット全体を失敗させる。
  **緩和済み**: このフィールドは `LotteryCampaignCreate`/`Update` から削除されたので、DB のデフォルト値 1 のままになる。
  抽選自体はまだユーザー単位で重複を除いていない。このフィールドを再び公開する前にそれを修正すること。すでに 1 より
  大きく設定されている行は変更されていない。`SELECT id FROM lottery_campaigns WHERE max_entries_per_user > 1` で確認する。
- [x] **7. IP ベースのレート制限が偽装可能。** `ProxyHeadersMiddleware(trusted_hosts="*")`（`main.py:70`）により、
  uvicorn 0.38 は `X-Forwarded-For` の *一番左* のホップを採用するが、これはクライアントが制御できる（Render は追記する
  だけで、取り除かない）。ヘッダーを変え続けることで、ログイン／登録の制限を回避できる。
  **修正計画あり:** `docs/plans/rate-limit-client-ip_JP.md`。
  **レビュー:** 「致命的」より「高」に近い — ログイン／登録の制限は破れるが、それだけでデータが漏れることはない。
  **コードは修正済み**（`project_status_JP.md` §4 の項目 49）: `ProxyHeadersMiddleware` を削除した。
  `rate_limit.client_ip()` が `X-Forwarded-For` の右から `TRUSTED_PROXY_HOPS` 番目のエントリを読み、ログインと
  パスワード再設定の依頼にはメールアドレスごとの制限も加わった。Render 側で残っている作業: ホップ数を計測して
  `TRUSTED_PROXY_HOPS` を設定する（`deployment_JP.md` §7）— それまではデフォルトの `0` により、すべての訪問者が
  1 つのバケットを共有する。
- [ ] **8. 行ロックを保持したままの PayPal キャプチャ、突き合わせ処理なし。** `finalize_paypal_payment` は、
  payment/ticket_type/products に対する `FOR UPDATE` を保持したまま `capture_order`（ネットワーク呼び出し、タイムアウト
  10 秒）を呼ぶ（`payment_service.py:153`、`:182`）。PayPal がキャプチャしたのにレスポンスがタイムアウトした、または
  こちらのコミットが失敗した場合 → 課金済みなのに DB は `pending`。Webhook が再び `capture_order` を呼ぶ → 422 already
  captured → 500 → 3 日間リトライされ、決して解決しない。Webhook は再キャプチャするのではなく、イベントを適用すべき。
  #30、#32 とあわせて設計する（同じ関数、同じ PayPal 呼び出し）。

## 🟠 高

- [x] **9. 同期的な処理をする `async def` のルート。** 161 個の非同期ハンドラーすべてが、同期的な SQLAlchemy、bcrypt、
  PayPal の httpx、boto3 を呼んでいる → イベントループをブロックする。素の `def` のルートならスレッドプールを使う。
  **ハンドラーは修正済み**: すべてのルートハンドラー（現在 163 個）は `def`（`architecture_JP.md` §2）。何かを await
  していた 6 個も変換した: `storage.save()` は同期になり、Webhook は非同期の依存性でボディを読む。アップロードと
  Webhook がスレッドプールで実行されることを TestClient で確認済み。S3 へのアップロードは最大で MAX+1 バイトしか
  読まなくなった（下記の「ファイル全体をメモリに読み込む」スメルを修正）。
  - ~~`app/db/session.py` で `pool_size`/`max_overflow` を明示的に設定する~~ — 対応済み（5 + 5、タイムアウト 10 秒）
- [x] **10. `DEBUG` のデフォルトが `True`**（`settings.py`）で、`deployment_JP.md` や `email_sender.py` のコメントと
  矛盾している。`DEBUG` が設定されていない環境では、リセットトークンがログに出力され、メールは送信されない。
  **修正済み**: `DEBUG` のデフォルトは `False` になり、`deployment_JP.md` と一致した。
- [ ] **11. Redis の障害 → 500。** `CacheService` に `RedisError` の処理がない。無効化はコミット後に実行されるので、
  実際には成功した注文で購入／決済が 500 になる。
  **修正計画あり:** `docs/plans/redis-outage_JP.md`（読み取りのフェイルオープン、ベストエフォートの無効化とメール
  送信、クライアントのタイムアウト）。
- [ ] **12. 放置された一般販売の PayPal チケットがファンを締め出す。** `pending_payment` は有効なものとして数えられる
  （`ticket_service.py:54`）が、一般販売のチケットには期限も掃除処理もない。
  **延期**: #26、#27 とあわせて後で修正する。
- [ ] **13. 転売防止の上限がキャンセル／拒否された注文も数える**（`order_service.py`、ステータスのフィルタなし）。
  ~~ロックの前に計算されている（並行した購入が両方とも通過しうる）~~ — **競合は修正済み**: `checkout` はカートの
  商品に対する `FOR UPDATE` の後に上限をチェックし、`fn_enforce_resale_cap` は合計の前に（購入者, 商品）で
  `pg_advisory_xact_lock` を取る（マイグレーション `d4a7c9e2f1b5`）ので、トリガー単体でも成り立つ。
  `tests/integration/marketplace/test_resale_cap_concurrency.py` で競合をテスト済み。ステータスのフィルタの方は
  まだ未解決。放置された PayPal の購入がこれを悪化させる: それぞれが永久に上限に数えられる `pending` の注文を残す
  （#27）ので、ファンは 1 つも所有していないのに `ResaleCapExceededError` に当たることがある。`confirmed` の注文だけを
  数えるべき。
  **スコープ外**: ユーザーによるキャンセルの経路（`cancel_placed_order`）はフロントエンドで使われておらず、現在の
  スコープに入っていない。ただし、拒否されたモック決済（`payment_service.py:34`）と放置された PayPal の注文（#27）は、
  そのエンドポイントがなくても上限に数えられる点に注意。
  **レビュー:** 修正はサービスのフィルタだけでは足りない。`fn_enforce_resale_cap` もステータスのフィルタなしで
  すべての注文を合計しているので、別途マイグレーションが必要。また、`confirmed` の注文だけを数えるようにすると、
  ファンはそれぞれ上限内に収まる `pending` の PayPal 注文を複数作り、すべてキャプチャできてしまう —
  `finalize_paypal_payment` がキャプチャの前に上限を再チェックする必要がある。
- [ ] **14. `cancel_placed_order` が在庫の戻し、返金、商品キャッシュの破棄を行わない。**
  **スコープ外**: フロントエンドはこのエンドポイントを使っておらず、現在のスコープに入っていない。
  **レビュー:** ルート自体は今も有効。`PATCH /order/cancel/{order_id}`（`router/marketplace/order.py:80`）には
  レート制限がなく、ファンは支払い済みで未発送の自分の注文を、返金も在庫の戻しもなくキャンセルできる。サービスが
  完成するまで、このルートを削除するか無効にする。
- [x] **15. カートの価格のずれ。** 商品を再度追加すると `total_price` は現在の価格で更新されるが、`Cart.price` は古い
  まま残る（`cart_service.py` の add_to_cart）。購入時は注文合計に `total_price` を、明細に `price` を使う → 両者が
  一致しない。
  **修正済み**: 商品を再度追加すると行の価格が付け直される（`price` と `total_price` の両方を現在の価格から）。
- [x] **16. コミット前にメールが送信される**（`checkout_ticket` / `checkout_won_ticket`）。
  **修正済み**: どちらの購入も `commit_or_raise` の後にだけ確認メールを送る。ユニットテストがその順序と、コミットが
  失敗したら何も送信されないことをチェックしている（古いコードに対しては失敗する）。
- [x] **17. Webhook の `KeyError`**: `resource.supplementary_data.related_ids.order_id` を持たないイベントタイプで
  発生 → 500 → PayPal がリトライする。
  **修正済み**: `paypal_client.order_id_from_webhook` は `CHECKOUT.ORDER.*`（`resource.id`）または
  `PAYMENT.CAPTURE.*`（`supplementary_data`）のイベントから注文 ID を読む。それ以外は 200 を返して無視する。注文 ID が
  見つかった後の処理は変わっていない（#8）。
- [ ] **26. 未払いの PayPal の注文が発送できてしまう。** PayPal の経路は、支払いの前に注文の `shipping_status` 行を
  `pending` で作成し（`payment_service.py:51`）、`ship_order` は `order.status` ではなく発送ステータスだけをチェック
  する（`order_service.py:202`）。放置された、またはまだキャプチャされていない注文がマネージャーの注文ページに表示され、
  発送済みにできてしまう。`ship_order` で `order.status == confirmed` を必須にすべき。
  **レビュー:** 延期を取り消す — このガードは #12 にも #27 にも依存しない（チェック 1 つとテスト 1 つ）。
  `update_shipping_status`（`order_service.py:164`）にも同じチェックが必要。
- [ ] **30. PayPal の `create_order` が行ロックを保持したまま実行される。** #8 と同じ種類で、キャプチャではなく
  購入時に起きる。`OrderService.checkout` はカートの商品を `FOR UPDATE` でロックし（`order_service.py:69`）、
  `checkout_ticket` はユーザーとチケット種別をロックする（`ticket_service.py:91`、`:99`）。どちらもその後、コミットの
  前に `create_payment` / `create_ticket_payment` を通じて `create_order`（ネットワーク呼び出し、タイムアウト 10 秒）を
  呼ぶ（`payment_service.py:46`、`:94`）。PayPal の呼び出しが遅いと、その商品やティアの他のすべての購入がブロック
  される。2026-11-13 のレビューで発見。
- [x] **28. `GET /shipping_addresses/fetch_byid/{id}` が常に 500 になり、所有者のチェックもない。**
  このルート（`app/router/marketplace/shipping.py:30`）には `get_current_user` の依存性がないのに、リミッターは
  `request.state.user` を読む `user_key` を使っている → `AttributeError`（リミッターは `RedisError` しか捕捉しない）→
  すべての呼び出しで 500。`TestClient` で確認（2026-09-29）。その裏で、`ShippingService.get_address_by_id` は ID だけで
  フィルタしているので、500 が修正されると他のユーザーの住所に対する IDOR になる。修正: 兄弟の `update`/`delete` の
  ルートと同じく、`get_current_user` を追加して `user_id` でフィルタする。
  **修正済み**（`project_status_JP.md` §4 の項目 47）: このルートはログインを必須とし、所有者でフィルタするように
  なった。兄弟の `update`/`delete` のクエリにも同じ穴（`user_id==user_id`、常に真）があり、あわせて修正した。

## 🟡 中

- [ ] **18.** `change_password_process` がリフレッシュトークンを失効させない（リセットは失効させる）。
  **レビュー:** 現状の影響は小さい — `create_tokens` がログイン時に他のすべてのトークンを失効させるので、その時点で
  有効なトークンは使用中の 1 つだけ。問題になるのは、そのトークン自体が盗まれている場合。
- [ ] **19.** パスワードリセットの JWT が期限切れまで再利用できる（`jti` やパスワードハッシュとの紐付けがない）。
- [ ] **20.** リフレッシュトークンが平文で保存されている。ログインのたびに他のすべてのセッションが失効する
  （`auth_service.py` の `create_tokens`）。
  **レビュー:** 欠陥なのは平文での保存だけ。1 ユーザー 1 セッションは文書化された設計（`create_tokens` のコメントを
  参照）。
- [x] **21.** `get_current_user`: `sub` がないと `uuid.UUID(payload.get("sub"))` が 500 になる。存在しないユーザーは
  401 ではなく 404 を返す。
  **修正済み**: `sub` がない、または不正な形式の場合と、存在しないユーザーの場合はすべて 401 を返す
  （`get_current_user_optional` では `None`）。
- [ ] **22.** レートリミッターの `INCR` + `EXPIRE` がアトミックでない（間でクラッシュすると → キーが期限切れに
  ならない）。`user_key` は暗黙的に `get_current_user` が先に実行されることに依存している。
  **半分修正済み**: カウンターは 1 つの `MULTI` トランザクション（`SET key 0 EX window NX` + `INCR`）で TTL 付きで
  作成・加算されるので、有効期限なしで存在することはない。`user_key` の順序への依存はまだ未解決。
- [ ] **23.** ページネーションされたページが `count=len(data)`（合計ではなくページのサイズ）を返す
  （`order_service.py:267`、`ticket_service.py:281`、`product_service.py:477`）。マネージャーの注文ページはすべての
  商品と注文の ID をメモリに読み込む。
- [ ] **24.** 抽選の計算量が O(応募数 × 希望数) + O(順位数 × キャンペーン数 × 応募数)。
- [ ] **25.** `notify_managers_of_draw_completion` がコミット後に失敗すると、Celery タスクの `except` がマネージャーに
  抽選が *失敗した* と通知する。`draw_lottery` 内で `commit_or_raise` の後にあるものなら何でもこれを引き起こす:
  完了通知自身のコミットや、Redis が落ちているときの `delete_cached_concert_detail`（#11）。マネージャーにはコミット
  済みの抽選が「失敗」と表示され、Celery はタスクを失敗として記録し、失敗通知のコミット自体も失敗して元のエラーを
  隠してしまうことがある。修正: コミット後のステップはベストエフォートとして扱い（ログに出し、再送出しない）、
  コミット前のエラーだけがタスクの失敗経路に到達するようにする。
  **修正計画あり:** `docs/plans/lottery-draw-post-commit_JP.md`（コミット後のステップをタスクに移す）。
- [ ] **27. 放置された PayPal のマーケットプレイス注文が永久に `pending` のまま残る。** ファンが PayPal で承認しない
  場合、`finalize_paypal_payment` は実行されない: 注文、その決済、発送ステータスが、期限も掃除処理もないまま
  `pending` に留まる。在庫は確保されず、カートもクリアされないので、ファンは再度購入できるが、古い注文が注文履歴と
  マネージャーの注文ページを散らかし、転売防止の上限に加算され（#13）、発送可能に見える（#26）。#12 と根本原因が同じ
  （PayPal の pending 状態に有効期限がない）なので、あわせて修正する。
  **延期**: #12、#26 とあわせて後で修正する。
- [ ] **31. PayPal の承認からキャプチャまでの間に在庫がなくなると、すべてが pending のまま残る。** キャプチャの
  時点でティアが売り切れ、または商品の在庫が不足していると、`finalize_paypal_payment` は何も変更せずに `None` を
  返す（`payment_service.py:142`、`:180`）: すでに PayPal で承認したファンには 404 が返り、チケットや注文は
  `pending` のまま残る。キャプチャはされていないのでお金は失われないが、#12 と #27 を悪化させる。代わりに決済を
  失敗にし、チケット／注文をキャンセルすべき。2026-11-13 のレビューで発見。
- [ ] **32. キャプチャの成否を注文のステータスだけで判断している。** `finalize_paypal_payment` は、キャプチャの
  レスポンスの最上位の `status == "COMPLETED"` を支払い済みとして扱い（`payment_service.py:154`、`:183`）、
  キャプチャ自体のステータス（`purchase_units[].payments.captures[].status`）を読まない。これは完了した注文でも
  `PENDING` や `DECLINED` になりうる。サンドボックスでは再現していない。キャプチャのステータスもチェックすべき。
  2026-11-13 のレビューで発見。
- [x] **29. `manager-*-page` の読み取りに認証もサーバー側の事務所スコープもない。**
  `GET /concerts/manager-events-page`、`/groups/manager-groups-page`、`/idols/manager-idols-page`、
  `/idols/manager-idol-form-page`、`/products/manager-products-page`、`/products/manager-product-form-page` は認証の
  依存性を取らず、商品系のものはクライアントが指定した `company_id` でフィルタする。データは公開の一覧と同じなので
  現時点で新たに漏れるものはないが、他のすべてのマネージャー向けルートにある RBAC を飛ばしており、レート制限もない。
  `GET /order/manager-orders-page` は例外で、正しくスコープされている。
  **修正済み**（`project_status_JP.md` §4 の項目 48）: 6 つすべてが `require_manager_or_admin` を必須とし、レート制限
  （`30/60s`、`user_key`）がかかり、マネージャーは自分の事務所の行だけを取得する。

## 🔵 コードスメル

- お金を `float` で扱っている（`total_price=float(...)`、`with_tax(float(...))`）。
- ~~読み取り専用の `/payment/status/*` エンドポイントが `PATCH` を使っている~~ — 修正済み: `GET` になった（フロント
  エンドの `payment.service.js` も同じリリースで切り替える必要がある）。
- ~~空のリストが 404 を返す~~ — 修正済み: すべてのリストのエンドポイントは `[]` を、ページのエンドポイントは空の
  ページオブジェクトを返す（2026-09-29）。
- ~~`/account/verify` が「認証済み」の場合に 401 を返す~~ — 修正済み: 認証済みなら `409`、不正なトークンや存在しない
  ユーザーなら `400`（`app/exception/common.py` に `ConflictError` を追加）。
- `app/` のどこにも `logging` がない — `print()` だけ。メールの失敗は握りつぶされ、リトライされない。
- ~~`verify_token_and_get_user_id` / `verify_rtoken_and_get_user_id` がほぼ重複~~ — 修正済み:
  `jwt_manager.decode_email_token(token, expected_type)` に統合した。
- ~~`CacheService` とサービスが相互にインポートしている~~ — 修正済み: 無効化を `app/cache/invalidation.py`
  （Redis のみ）に分離し、`CacheService` がそれを継承する（`architecture_JP.md` §2）。
- ~~アップロードの拡張子をクライアントのファイル名から取っている — `Content-Type: image/png` の `.html` が、API の
  オリジン上で `StaticFiles` によって HTML として配信される（格納型 XSS）~~ — 修正済み: 拡張子はホワイトリストに
  ある Content-Type から決める（`storage.IMAGE_EXTENSIONS`）。~~S3 の経路がサイズチェックの前にアップロード全体を
  読み込む~~（#9 で修正済み）。
- ~~PayPal の `pg_payment_id` が、本物のキャプチャ ID ではなく `generate_mock_id()` から設定されている（返金に必要）~~
  — 修正済み: `paypal_client.capture_id_from_response` を通じてキャプチャのレスポンスから設定する。
- ~~大文字のローカル変数 `MAX_RANK`、すべての呼び出し元が `"JPY"` を渡すのに `create_order` の通貨のデフォルトが
  `"USD"`、`main.py` に残ったチュートリアルのコメント~~ — 修正済み: `max_rank` に改名し、デフォルトは `"JPY"` に
  なり、コメントは削除した。

## 推奨する順序（2026-11-13 更新）

これまでに修正済み: #1、#3、#4、#5、#6（緩和）、#7、#9、#10、#15、#16、#17、#21、#22 の半分、#28、#29、
コードスメル 8 件。

1. ~~すぐにできるもの: #10、#15、#16、#17~~（完了）。
2. **新たにすぐできるもの:** #26 発送の前に `confirmed` を必須にする、#14 キャンセルのルートを削除または無効にする。
3. **セキュリティ:** ~~#28 壊れていて保護されていない住所の取得~~（完了）、~~#7 偽装可能な IP のレート制限~~
   （コードは完了。Render で `TRUSTED_PROXY_HOPS` を設定する）、~~#29 認証のないマネージャーページ~~（完了）。
4. **データの整合性とお金:** #2 商品の削除で注文履歴が消える（`RESTRICT` へのマイグレーション + 論理削除または
   ブロック）。
5. **計画あり:** #11 Redis 障害の処理（計画は `docs/plans/redis-outage_JP.md`）を #25（計画は
   `docs/plans/lottery-draw-post-commit_JP.md`）とあわせて — Redis の修正で #25 の原因が 1 つなくなる。
6. **認証:** #18、#19、その後 #20 のうち平文保存の部分。
7. **PayPal の pending 状態:** #12（放置されたチケットがファンを締め出す）と #27（放置された注文が期限切れに
   ならない）を定期的な掃除処理で直し、#31 と #13 もあわせて（pending の注文が期限切れになるか、キャプチャ時に
   再チェックされて初めて、上限は `confirmed` の注文だけを数えられる）。
8. **先に設計が必要:** #8 ロック中の PayPal キャプチャ／Webhook の突き合わせ、#30 と #32 もあわせて。
9. **都合のよいときに:** #22、#23、#24。
