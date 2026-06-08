# DEMO RUN RESULT

## 実行コマンド

```bash
python -m pytest -q
python momentum_screening_pure.py --demo --output-dir demo_output
```

## このレビュー環境での結果

2026-06-08 に実行を試みましたが、コンテナに `numpy` がなく、依存関係の取得先も `403 Forbidden` を返したため、pytest収集時点で停止しました。これはコードが検知したデータ障害ではなく、レビュー環境の依存関係制約です。`python -m py_compile momentum_screening_pure.py tests/test_momentum_screening_pure.py` と `git diff --check` は成功しています。

依存関係をインストール可能な環境では、README記載のコマンドで固定seedのオフラインデモを実行できます。デモは実市場データを取得せず、`demo_output/` に品質レポート、全スコア、最大12候補、確認用注文、manifestを生成します。

## 正常時のmanifest形式（例示）

```json
{
  "mode": "demo",
  "regimes": {"US": "BULL", "JP": "BULL"},
  "advisory_exposure": 1.0,
  "fx_usdjpy": 155.0,
  "warnings": [],
  "cash_remainder_jpy": 0
}
```

上記は形式例であり、この環境で生成された投資結果ではありません。実際の残存キャッシュと警告は実行時の `run_manifest.json` を正としてください。
