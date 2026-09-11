# デイトレ・スイング投資運用成績トラッカー

運用成績・売買履歴の管理に、通常タブの「銘柄判断」を統合しています。
Googleログインと銘柄辞書を共有し、判定処理は同梱のPythonコードを再利用します。

## 通常アプリの起動

正規リポジトリのPowerShellで実行します。

~~~powershell
.\start-app.ps1
~~~

PCのURLは [通常アプリ](http://127.0.0.1:8766/) です。
Googleログイン後、下部または左側の［銘柄判断］を開きます。
アクセスコード・別のUAT画面・Streamlitの埋め込みは使いません。
停止は起動ターミナルで Ctrl+C です。

初回準備、公開、スマホ接続、保存先は [本番統合ガイド](docs/PRODUCTION_INTEGRATION.md) を参照してください。
現在のGitHub Pagesへ新機能を反映するには、Python APIのHTTPS公開先を設定する必要があります。
ローカル起動の確認と、インターネット公開の完了は区別しています。

## 構成

- index.html / app.js / 既存mjs：従来の運用成績・売買管理
- judgment.mjs / judgment.css：通常タブの入力、結果、履歴
- app_server.py / judgment/：本人確認、既存判定コードへの接続、本人別保存
- investment/：正本仕様、計算、Provider、検証コードとデータ
- judgment-config.json：画面から判定APIへの接続先
- [本番統合の確認結果](docs/PRODUCTION_INTEGRATION_RESULT.md)

従来のFirebase設定・Firestore保存先・売買データは変更していません。
旧UAT用のコードと検証資料は開発用に保持しています。
旧iframe用 investment.mjs / investment.css は通常タブへの置換に伴い削除しました。

本番反映の準備状況とrollbackは [公開リリース手順](docs/PRODUCTION_RELEASE.md) を参照してください。
