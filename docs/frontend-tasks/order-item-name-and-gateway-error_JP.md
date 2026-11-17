# フロントエンドのタスク: 注文明細の商品名と PayPal ゲートウェイのエラー

[English](order-item-name-and-gateway-error.md) | 日本語

**バックエンドの変更:** `docs/bugs_JP.md` #34 と #36。どちらも破壊的ではなく、追加のみ。
**返信先:** `docs/backend-tasks/live-e2e-findings.md` の項目 1 と 3。

## 1. すべての注文明細に `product_name`

`GET /order/fetch_placed_order`、`GET /order/single_placed_order/{id}`、`POST /order/checkout` が返す `Order` に
`items[].product_name` が加わった。無効化された商品も同じ。

- `OrderDetailsPage.vue`: `item.product_name` を表示し、ない場合だけカタログの検索にフォールバックする。これで、無効化された
  商品の「Unknown product」がなくなる。
- `[known-gap]` と注釈している本物のバックエンドの e2e テストは、名前を検証できる。
- 画像のフィールドは加えていない。無効化された商品の過去の注文には、まだカバー画像がない。

## 2. チェックアウト時に PayPal が使えない

`gateway: "paypal"` の `POST /order/checkout`、`POST /tickets/checkout`、`POST /tickets/{id}/checkout` は、PayPal に
接続できない、またはリクエストが拒否されたとき、**502** `{"detail": ..., "code": "payment_gateway_unavailable"}` を返す。
何も作られない: カート、在庫、チケットは変わらないので、ファンはやり直せる。

- このコードには、「PayPal が今応答していません。カートは変わりません。もう一度お試しください。」のようなメッセージを、
  両方のロケールで表示する。
- キャプチャのエンドポイントと Webhook は対象外で、処理されない 500 を返すことがある。
