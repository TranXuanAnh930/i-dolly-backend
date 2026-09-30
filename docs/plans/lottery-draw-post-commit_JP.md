# 修正計画: コミット済みの抽選を失敗として報告してはならない（bugs_JP.md #25）

[English](lottery-draw-post-commit.md) | 日本語

**ステータス:** 計画済み、未着手（2026-09-27）。抽選のコード: 手書きで実装する予定。このドキュメントは設計のみ。

## 問題

`LotteryDrawService.draw_lottery`（`app/services/events/lottery_draw_service.py`）は次のように終わる:

```python
commit_or_raise(db)                                             # ① the draw is saved
CacheInvalidation.delete_cached_concert_detail(concert_id)      # ② Redis
ConcertService.notify_managers_of_draw_completion(db, concert)  # ③ inserts + a second commit
return LotteryResult(...)
```

`draw_lottery_task`（`app/tasks/lottery.py`）は呼び出し全体を 1 つの `except Exception` で包んでおり、そこで
ロールバックし、事務所のマネージャーに `lottery_draw_failed` を送り、再送出する。① の **前** の失敗（抽選が本当に失敗
し、何も保存されていない）と、① の **後** の失敗（抽選は保存済みで、副作用だけが失敗した）を区別できない。

① の後の発生要因:
- Redis が落ちているときに ② が `redis.ConnectionError` を送出する（#11）。
- ③ のコミットが失敗する（接続の切断、トリガーのエラー）。

それが起きたときの結果:
- 当選者は `pending_payment` のチケットを持ち、席は確保され、キャンペーンは `drawn` になり、ファンはすでに
  `lottery_result` 通知を受け取っている（それらはコミット ① に含まれていた）— なのに、マネージャーには抽選が
  **失敗した** と伝えられる。
- Celery はタスクを `FAILURE` として記録する。
- 再実行したマネージャーは「No open lottery campaigns」を受け取る（キャンペーンは `drawn` になっている）— データは
  安全だが、メッセージのせいで状況が実際より悪く見える。
- 接続の切断によって ③ が失敗した場合、`notify_managers_of_draw_failure` 自身のコミットも失敗し、その例外がログ上で
  元の例外に置き換わってしまう。

## 決定事項

**コミットが境界である。** コミット ① の前のエラーは抽選の失敗であり、その後のものはすべてベストエフォートの副作用
として、ログに出すだけで失敗の経路には決して到達させない。

選んだ形 — **コミット後のステップをサービスからタスクに移す**（案 B）:

- `draw_lottery` は `commit_or_raise(db)` で終わり、`LotteryResult` を返す。キャッシュの無効化や、マネージャーへの完了
  通知はもう行わない。
- `draw_lottery_task` は、既存の `try/except` の中で抽選を実行し（失敗の経路は変わらない）、その後、コミット後の
  ステップを `try/except` の **外** で、それぞれ個別のガードで実行する。

却下した代替案（案 A）: ② と ③ をサービスに残し、それぞれを個別の `try/except` で包む。差分は小さいが、その場合
「コミット済み = 成功」というルールは、将来のコミット後の行すべてが自分の try/except を忘れないことに依存してしまう。
B なら、タスクの構造がそれを強制する: 抽選の呼び出しの後にあるものは、何ひとつ失敗の分岐に到達できない。

スコープ外: 完了通知のリトライ。③ が失敗した場合、マネージャーは完了通知を受け取らないが、抽選結果は結果ページ
（`GET /lottery_entries/concert/{concert_id}/results`）で引き続き確認できる。ログに出し、受け入れる。

## 目標の形（スケッチであり、最終的なコードではない）

```python
@celery_app.task(name="app.tasks.lottery.draw_lottery")
def draw_lottery_task(concert_id: str, user_id: str) -> dict:
    db = session()
    try:
        try:
            current_user = db.get(Users, uuid.UUID(user_id))
            result = LotteryDrawService.draw_lottery(db, current_user, uuid.UUID(concert_id))
        except Exception:
            # Nothing was committed: report the failure.
            db.rollback()
            ...notify_managers_of_draw_failure (guarded, see step 3)...
            raise

        # The draw is committed. Side effects below are best-effort.
        _after_draw(db, uuid.UUID(concert_id))
        return result.model_dump(mode="json")
    finally:
        db.close()


def _after_draw(db, concert_id) -> None:
    try:
        CacheInvalidation.delete_cached_concert_detail(concert_id)
    except Exception:
        logger.exception("draw %s: cache invalidation failed", concert_id)
    try:
        concert = db.get(Concert, concert_id)
        ConcertService.notify_managers_of_draw_completion(db, concert)
    except Exception:
        db.rollback()
        logger.exception("draw %s: completion notification failed", concert_id)
```

## 手順

1. **サービス**: `draw_lottery` から ② と ③ を削除し、`commit_or_raise(db)` の直後に返すようにする。他で使われて
   いなければ、使われなくなった `CacheInvalidation`/`ConcertService` のインポートを削除する。
2. **タスク**: 上記のとおり `draw_lottery_task` を分割する — 抽選は失敗用の `try` の中、コミット後のステップは
   `_after_draw` の中で、それぞれ個別にガードする（Redis の失敗で通知が飛ばされてはならない）。
3. **失敗通知もガードする**: `notify_managers_of_draw_failure` を、ログに出すだけの個別の `try/except` で包み、そこで
   の失敗が元の例外を置き換えないようにする。その後、元の例外を `raise` する。
4. **ロギング**: `app/tasks/lottery.py` で `logging.getLogger(__name__)` を使う（#11 の計画での `logging` の初導入と
   共通）。
5. **サービスを直接呼ぶ呼び出し元**: `tests/integration/events/test_lottery_concurrency.py` はタスクを通さずに
   `draw_lottery` を呼ぶ。手順 1 の後、これらのテストでは完了通知もキャッシュの削除も発生しなくなる。どちらかに
   ついてアサートしている結合テストはない（2026-09-27 に確認）。`scripts/seed.py` はこれを呼ばない。
6. **テスト**（`tests/unit/tasks/test_lottery_task.py`、新規。`session`、サービス、`ConcertService` をパッチする）:
   - 完了通知が送出する → タスクは結果を返し、`notify_managers_of_draw_failure` は呼ばれず、再送出もしない。
   - キャッシュの無効化が送出する → 完了通知は送られ、タスクは結果を返す。
   - 抽選が送出する → ロールバックし、失敗通知が送られ、元の例外が再送出される。
   - 抽選が送出し、**かつ** 失敗通知も送出する → **元の** 例外が伝播する。
   - `tests/unit/events/test_lottery_draw_service.py`（サービスから `notify_managers_of_draw_completion` が呼ばれることを
     アサートしている、143 行目あたり）を更新 → 呼ばれないことをアサートする。その振る舞いは今後タスクのテストが
     担う。
   - ネガティブコントロール: 最初の 2 つのテストは現在のコードに対して失敗する。
7. **ドキュメント**: `bugs.md` の #25 にチェックを付ける。`project_status.md` §8（抽選ジョブ）— 完了通知は今後、
   コミットの後にタスクがベストエフォートで送る。`docs/database-design.md` の抽選のシーケンス図が、完了通知を抽選の
   トランザクション内に描いている場合はそれも更新する。

## 関連

- **#11**（`docs/plans/redis-outage_JP.md`）により、② はそれ自体では送出しなくなる。それでもこの修正は必要: ③ は
  独立して失敗しうるし、この境界は将来のあらゆるコミット後のステップについて成り立つべきである。
- **#24**（抽選の計算量）と **#6**（ユーザー単位の重複除去）は同じサービスに触れるが、これとは独立している。
