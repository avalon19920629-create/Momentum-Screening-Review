# L.U.M.U.S.-8 Momentum Screening PURE Edition

日米株から各6銘柄を選ぶ、監査可能性と誤作動耐性を優先したモメンタム候補生成器です。これは**投資助言・自動発注システムではありません**。Yahoo Financeデータを利用するため、出力は必ず人手で確認してください。

## 実行方法

```bash
python -m pip install -r requirements.txt
python momentum_screening_pure.py --demo --output-dir demo_output
python momentum_screening_pure.py --output-dir live_output --sector-map sector_map.csv
python -m pytest -q
```

`--demo` は固定seed・固定最終日を使い、ネットワークなしで再現可能です。`sector_map.csv` は `Ticker,Sector` 列を持つ任意ファイルです。未指定時はセクター集中を計測できない旨を警告します。

## 出力

| ファイル | 用途 |
|---|---|
| `quality_report.csv` | 取得不能、履歴不足、欠損過多、陳腐化などの全銘柄判定 |
| `all_scores.csv` | 全通過銘柄の指標、適格性、スコア |
| `selected_portfolio.csv` | 各市場最大6銘柄と制約付き逆ボラウェイト |
| `review_required_orders.csv` | 人手確認用。すべて `REVIEW_REQUIRED`、指値は空欄 |
| `manifest.json` | as-of、設定、レジーム、FX、警告、残存キャッシュ |

## 運用ルール

- 四半期スクリーニングを基本とし、途中売買は上場廃止・データ異常等の例外時だけに限定してください。
- `review_required_orders.csv` をブローカーへ直接投入しないでください。価格、通貨、株式分割、売買単位、指値、税・手数料を確認してください。
- `UNKNOWN` レジーム、欠落セクター、縮小フォールバックユニバース、候補12銘柄未満は運用停止または承認対象です。
- 現行構成銘柄との比較、売買回転率、税・スリッページを上位の運用プロセスで評価してください。

## マージ前の最終確認デモ

依存パッケージやネットワークがない監査環境でも、以下で決定論的な最終確認シナリオを実行できます。デモは、取得不能・履歴不足・UNKNOWNレジーム・FX取得不能を意図的に含みます。

```bash
python momentum_screening_pure.py --demo --output-dir final_validation_output 2>&1 | tee final_validation_output.log
python -m unittest -v tests.test_portable_demo
```

生成物は次の5ファイルと標準出力ログです。

- `final_validation_output/quality_report.csv`
- `final_validation_output/all_scores.csv`
- `final_validation_output/selected_portfolio.csv`
- `final_validation_output/review_required_orders.csv`
- `final_validation_output/manifest.json`
- `final_validation_output.log`

2026-06-08の実行サンプルでは、40銘柄中36銘柄を受理し、4銘柄を除外しました。除外理由は `insufficient_history=2`、`not_downloaded=2` です。US/JPを各6銘柄選定し、ウェイト範囲は5.56%〜11.25%でした。JPレジームを意図的に`UNKNOWN`としたため、BULL扱いせず助言稼働率は60%です。FXを取得不能にしたため、米国6注文は`BLOCKED_FX_MISSING`、日本6注文は`REVIEW_REQUIRED`です。日本株注文はすべて100株単位です。

実行済みの完全なサンプルは `final_validation_output/`、標準出力は `final_validation_output.log`、確認結果の説明は `FINAL_VALIDATION_REPORT.md` に保存しています。
