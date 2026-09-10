# デイトレ・スイング投資運用成績トラッカー

運用成績・売買履歴の管理に「新規銘柄判定」を統合した個人用UAT版です。
従来のFirebase保存を維持し、投資判定はPythonの計算処理と専用履歴を使用します。

## 起動

正規リポジトリのPowerShellで実行します。
初回準備・アクセスコード・スマホ接続は [統合UATガイド](docs/INTEGRATED_UAT.md) を参照してください。

~~~powershell
.\start-uat.ps1 -Lan
~~~

PCは http://127.0.0.1:8765/ 、スマホは起動時に表示するLAN用URLへアクセスします。
入口のアクセスコードは起動ターミナルまたは .runtime/uat-access.html にあります。
停止は起動ターミナルで Ctrl+C です。

## 構成

- index.html / app.js / *.mjs：従来の運用成績・売買管理
- investment/：判定の正本、Python処理、入力、3時間軸評価、履歴、実銘柄比較
- investment.mjs / investment.css：トラッカー内の判定メニューと画面
- uat_server.py：同じURLで両機能を提供する個人用UATサーバー
- [統合設計](docs/INTEGRATION_DESIGN.md)、[確認結果](docs/INTEGRATION_RESULT.md)

既存GitHub PagesだけではPython処理を実行できません。将来の外部公開にはPrivateリポジトリ、
HTTPS、認証、永続保存先の設定を確認します。現時点の統合UATはPC／同じWi-Fiで利用します。
