# フロントエンドのタスク: パスワード変更後もセッションを保つ。リセットのリンクは 1 回だけ使える

[English](password-session-and-reset-links.md) | 日本語

**バックエンドの変更:** `docs/bugs_JP.md` #18 と #19（ブランチ `fix/password-sessions-and-reset-links`）。
**種類:** 破壊的変更ではないが、予期しないログアウトを避けるためにタスク 1 が必要。これがないと、パスワードを
変更したファンは、ログインしたままにならず、現在のアクセストークンの期限が切れた時点でログアウトされる。
**参照:** リクエストとレスポンスの正確な形は `docs/api-spec_JP.md` にある。以下のファイル名は `i-dolly-frontend` の
もの。

## 1. バックエンドで変わったこと

### 1a. パスワードを変更するとセッションが入れ替わる（#18）

`PUT /profile/change-password` は、アカウントのすべてのリフレッシュトークンを失効させてから、呼び出し元に新しい
ペアを発行するようになった。レスポンスは `POST /account/refresh` と同じ形:

| | 変更前 | 変更後 |
|---|---|---|
| 本文 | `{"msg": "Password changed succesfully"}` | `{"msg": "...", "access_token": "<新しい JWT>"}` |
| Cookie | 変わらない | 新しい `refresh_token` の Cookie（httpOnly、Secure、SameSite=None） |
| 古いリフレッシュトークン | 有効なまま | 失効: それを使った `POST /account/refresh` は `401` を返す |

`old_password` が間違っている場合は、これまでどおり `400 incorrect_password` を返し、何も変わらない。

### 1b. リセットのリンクは 1 回だけ使える（#19）

`POST /profile/set-password` は、すでに使われたトークンや、別の方法でパスワードが変わる前に発行されたトークンに
対して `401 invalid_token` を返す。このバックエンドのデプロイより前にメールで送られたリンクも拒否される（いずれに
せよ、まもなく期限切れになるもの）。

## 2. フロントエンドのタスク

### タスク 1: パスワード変更後もセッションを保つ

`UsersService.changePassword`（`src/services/auth/users.service.js`）は credentials なしでリクエストを送るので、
ブラウザは新しい Cookie を無視し、新しいアクセストークンを受け取る処理もない。

- `AuthService.refreshTokens` が `POST /account/refresh` を呼ぶのと同じように、`withCredentials: true` 付きで
  リクエストを送る。これがないと `Set-Cookie` ヘッダーは捨てられる。
- 成功したら、`refreshTokens` と同じ方法で `response.data.access_token` を保存する（Bearer と有効期限）。
  `src/services/auth/auth.service.js` の `_setAuthData` は private なので、同じ処理を複製するのではなく、小さな
  `AuthService.applyAccessToken(accessToken)`（など）を公開する。
- `AccountSettingsPage.vue` はそれ以外の変更は不要: 成功のトーストはそのまま。

### タスク 2: リセットページのメッセージ

`src/pages/auth/ResetPasswordPage.vue` は、`invalid_token` に対してすでに `error.message`（「このリンクは期限切れ
です。新しいリンクをリクエストしてください。」に相当）を表示している。使用済みのリンクも同じコードになったので、
`src/i18n/locales/en.js` と `ja.js` の文言を広げる。例:「このリンクは期限切れか、すでに使用されています。新しい
リンクをリクエストしてください。」パスワード再設定ページへのリンクは残す。

## 3. 受け入れチェックリスト

- [ ] アカウント設定でパスワードを変更し、アクセストークンの有効期間を過ぎてもアプリを使い続ける: ログアウト
      されず、ネットワークタブで `POST /account/refresh` が成功している。
- [ ] 同じアカウントでログインしていた 2 つ目のブラウザは、次のリフレッシュでログアウトされる。
- [ ] 現在のパスワードが間違っている場合は既存のエラーが表示され、セッションは影響を受けない。
- [ ] リセットのリンクを 2 回目に開くと、期限切れまたは使用済みのメッセージが、新しいリンクを依頼する手段と
      ともに表示される。
- [ ] リセットのリンクを依頼し、アカウント設定でパスワードを変更した後にそのリンクを開くと、同じメッセージが
      表示される。

## 4. スコープ外

- 1 アカウント 1 セッションは変わらない: どこかでログインすると、他のセッションは引き続き終了する。
- リフレッシュトークンは、引き続きデータベースに平文で保存されている（`docs/bugs_JP.md` #20）。
