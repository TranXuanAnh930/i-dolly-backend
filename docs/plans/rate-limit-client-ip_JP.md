# 修正計画: レート制限のための信頼できるクライアント IP（bugs_JP.md #7）

[English](rate-limit-client-ip.md) | 日本語

**ステータス:** 計画済み、未着手（2026-09-26）。

## 問題

`ip_key` は `request.client.host` をキーにして制限をかける。`ProxyHeadersMiddleware(trusted_hosts="*")` はそれを
`X-Forwarded-For` の **一番左** のエントリから設定するが、これはクライアントが書くものであり、Render は本物の IP を
右側に追記する。一番左の偽のエントリを変え続けることで、すべての IP 制限（ログイン、登録、パスワード忘れ、
パスワード設定、認証）を回避できる。TestClient で再現: 偽装したヘッダーでパスワードを間違えたログインを 30 回 →
429 は 0 回（偽装なしの同じ IP → 429 が 20 回）。

ミドルウェアを削除するのも答えにはならない: そうするとすべての訪問者が Render のプロキシの IP を共有するので、
1 つのバケットで全員がレート制限されてしまう。クライアントの IP は、自分たちのプロキシだけを飛ばして右から読む
必要がある。

## 手順

0. **Render 上でのホップ数を計測する。** 一時的に `request.headers.getlist("x-forwarded-for")` と
   `request.client.host` をログに出してデプロイし、`curl -H "X-Forwarded-For: 1.2.3.4" https://<render-url>/` を
   実行する。`1.2.3.4` の後ろにあるエントリの数が **N**（信頼するプロキシのホップ数）で、本物の IP は位置 `-N` に
   ある。ログの行は削除する。
1. **設定:** `app/config/settings.py` に `TRUSTED_PROXY_HOPS: int = 0`（0 = プロキシなし、ヘッダーを無視する）。
   Render ではこれを N に設定する（`render.yaml`、`docs/deployment.md`）。
2. **`app/cache/rate_limit.py` の `client_ip(request)`**。`ip_key` から使う:
   - hops == 0 → `request.client.host`。
   - それ以外は、すべての `X-Forwarded-For` ヘッダーを結合し（`getlist`、カンマで分割）、`entries[-hops]` を取る。
   - リストが `hops` より短い場合や、エントリが有効な IP でない場合（`ipaddress.ip_address`）は、接続元の
     アドレスにフォールバックする。
3. **`main.py` から `ProxyHeadersMiddleware` を削除し**、「クライアントの IP は何か」を 1 つの関数が担うようにする。
   先に `request.url` / `url_for` を grep して、その `X-Forwarded-Proto` の処理に依存しているものがないことを確認する
   （リンクは `settings.BASE_URL` から組み立てている）。
4. **ログイン失敗に対するアカウント単位の制限**（IP の制限では、本物の IP を多数持つ攻撃者は止められない）:
   - キーは `rate:login_fail:{email.lower()}`、例えば 15 分で 5 回の失敗。
   - `login` ルーター内で: 上限を超えたら → 汎用的なメッセージで 429（アカウントが存在するかどうかを明かさない）。
     失敗時は、有効期限をアトミックに設定しつつ加算する（パイプラインまたは `SET … NX EX`、bugs.md #22 を参照）。
     任意で、成功時にクリアする。
   - パスワード忘れにも同じ考え方で、メールアドレスをキーにする（例: 1 時間に 3 回）。
   - `rate_limit.py` にヘルパー `record_login_failure(email)` / `login_attempts_exceeded(email)` を置く。
5. **テスト:**
   - ユニット、`client_ip`: hops 0 はヘッダーを無視する。hops 1 で `fake, real` → real。hops 2 で
     `fake, real, cdn` → real。複数のヘッダーを結合する。短いリスト／不正な IP → 接続元。
   - リグレッション: `TRUSTED_PROXY_HOPS=1` で、一番左に毎回異なる偽のエントリ、右側に同じ本物の IP を付けて
     11 回ログイン → 11 回目が 429。
   - アカウント単位: 1 つのメールアドレスで 6 つの異なる IP から 6 回失敗 → 6 回目が 429。別のメールアドレスは
     引き続き使える。
6. **ドキュメント:** bugs.md #7（あわせて修正したなら #22 も）、`deployment.md`（`TRUSTED_PROXY_HOPS` + 手順 0 の
   確認）、`architecture.md` §3（`client_ip()` をキーにしたレート制限 + アカウント単位の制限）。
7. **本番での確認:** 偽の `X-Forwarded-For` を付けた約 12 回のログインリクエスト → 429 が返る。

## N の選び方

大きすぎる → クライアントが書いたエントリを信頼してしまう（このバグ）。小さすぎる → 全員がプロキシのバケットを
共有してしまう（元の問題）。推測せずに計測すること（手順 0）。

**ファイル:** `app/config/settings.py`、`app/cache/rate_limit.py`、`main.py`、`app/router/identity/auth.py`
（+ パスワード忘れのための `user.py`）、新しいユニット／結合テスト、`render.yaml`、`docs/deployment.md`、
`docs/architecture.md`、`docs/bugs.md`。
