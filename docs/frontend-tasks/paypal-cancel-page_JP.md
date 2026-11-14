# フロントエンドのタスク: ファンが PayPal で取りやめたら購入手続きをキャンセルする

[English](paypal-cancel-page.md) | 日本語

**バックエンドの変更:** `docs/bugs_JP.md` #12 と #27（ブランチ `fix/release-abandoned-paypal`）。
**種類:** 破壊的変更ではない。このタスクがなくても、バックエンドはファンが次に購入手続きをしたときに、放置された
購入手続きを片付ける。このタスクで、キャンセルが即座に行われ、ページの文言も正確になる。
**参照:** `docs/api-spec_JP.md` §6 の PayPal のフロー（ステップ 6 と 7）と `POST /payment/paypal/cancel/{pg_order_id}`。
以下のファイル名は `i-dolly-frontend` のもの。

## 1. バックエンドで変わったこと

- 新しい `POST /payment/paypal/cancel/{pg_order_id}`（ファンのみ）。呼び出し元の pending の PayPal の決済と、それが
  支払おうとしていたものをキャンセルする: 一般販売のチケットは `cancelled` になり、注文は `cancelled` になって発送
  ステータスも `cancelled` になる。抽選の当選のチケットは期限まで `pending_payment` のまま。`PaymentResponse`
  （`status: "cancelled"`）を返すか、決済が存在しない、呼び出し元のものでない、またはすでにキャプチャ済みか
  キャンセル済みのときは `404` を返す。
- ファンの次の購入手続きも、本人の pending の PayPal の購入手続きをキャンセルする（チケットは同じ公演、
  マーケットプレイスは pending のすべての注文）。これについてフロントエンドで行うことはない。

## 2. フロントエンドのタスク

### タスク 1: キャンセルページからエンドポイントを呼ぶ

`src/pages/payment/PaypalCancelPage.vue` は現在、情報を表示するだけ。PayPal は `?token=<PayPal の注文 ID>` を付けて
ファンをこのページに戻す。リターンページがキャプチャに渡すのと同じ `token`。

- `src/services/payment/payment.service.js` の `capturePaypal` の隣に `PaymentService.cancelPaypal(pgOrderId)` を
  追加する: 認証付きの `POST payment/paypal/cancel/{pgOrderId}`。
- ページの `created()` で、`PaypalReturnPage.vue` と同じように `this.$route.query.token` を読み、それを呼ぶ。`404` は
  成功として扱う: 購入手続きはすでに決着している（例: 別のタブでの後の購入手続きによって）。どちらの場合もページを
  表示する。ネットワークエラーのときも、ページは表示する。

### タスク 2: 文言を更新する

`src/i18n/locales/en.js` と `ja.js` の `paypalCancel.note` は、注文が「pending として保存されている」と書いている。
今はキャンセルされる。文言の案:「PayPal で承認する前にキャンセルしたので、請求はされず、この購入手続きは
キャンセルされました。いつでもやり直せます。」抽選の当選の場合、チケットは期限まで確保されたまま。ページがそれを
判別できる場合は（現在はできない）、代わりにそう書く。

## 3. 受け入れチェックリスト

- [ ] PayPal でのチケットの購入手続きを始め、PayPal で「キャンセルして戻る」を押す: キャンセルページが表示され、
      ネットワークタブで `POST /payment/paypal/cancel/...` が 200 を返し、履歴でチケットがキャンセル済みと表示される。
- [ ] その直後に、同じ公演のチケットを購入できる。
- [ ] マーケットプレイスの注文でも同様に、履歴でキャンセル済みと表示される。
- [ ] キャンセルページを 2 回目に開く（再読み込み）と、ページは普通に表示され、404 はエラーとして表示されない。
- [ ] キャンセルせずに PayPal のタブを閉じ、同じ公演のチケットを再び購入できる。

## 4. スコープ外

- 二度と戻らないファンが残した pending の購入手続きは、履歴に引き続き pending と表示される。
- 未払いの抽選の当選は変わらない。
