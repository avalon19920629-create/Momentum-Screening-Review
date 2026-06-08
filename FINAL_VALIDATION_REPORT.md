# マージ前・最終実行確認

## 実行条件

- 実行日: 2026-06-08
- デモ価格as-of: 2026-06-05
- モード: `portable_demo_final_validation`（固定seed、ネットワーク不要）
- 意図的障害: 履歴不足2、取得不能2、JPレジームUNKNOWN、USD/JPY取得不能

## 実行コマンド

```bash
python momentum_screening_pure.py --demo --output-dir final_validation_output 2>&1 | tee final_validation_output.log
python -m unittest -v tests.test_portable_demo
```

## 結果

| 確認事項 | 結果 |
|---|---|
| 除外銘柄と理由 | 4件。`insufficient_history=2`, `not_downloaded=2` |
| UNKNOWNレジーム | JP=`UNKNOWN`。BULL扱いせず助言稼働率60% |
| 地域別選定 | US=6、JP=6 |
| 候補不足警告 | 制御プローブで `eligible candidates 3/6` 警告を確認 |
| ウェイト制約 | 5.56%〜11.25%。全銘柄4%〜12%内 |
| 日本株ロット | すべて100株単位 |
| FX取得不能 | 米国6件を `BLOCKED_FX_MISSING`、かつ全行 `Review_Required=True` |
| 低ボラ偏重 | 選定銘柄に全母集団の低ボラ第1四分位より高ボラの銘柄を含む |
| セクター集中 | 最大3銘柄。4銘柄以上のセクターなし |
| manifest | 設定、除外集計、レジーム方針、助言稼働率、注文状態、警告、全検証フラグを保存 |

`manifest.json` の `validation_checks` は全項目 `true` です。出力サンプルは `final_validation_output/`、標準出力ログは `final_validation_output.log` を参照してください。

## 注意

これは異常系を含む決定論的な監査デモです。実市場データでの最終運用承認を代替しません。ライブ実行では契約データとの照合、point-in-timeユニバース、税・手数料・スリッページ、現保有との差分確認が必要です。
