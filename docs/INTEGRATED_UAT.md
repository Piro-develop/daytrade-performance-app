> この文書は旧UAT版の記録です。通常アプリは [本番統合ガイド](PRODUCTION_INTEGRATION.md) を参照してください。

# 統合UATの使い方

## 通常の起動

正規リポジトリ daytrade-performance-app のPowerShellで実行してください。
コードと仕様はこのリポジトリ内で完結します。このPCでは新規 .venv のNumPy DLLがWindows実行制限で拒否されたため、確認済みの既存Python環境を .runtime/python-path.txt に指定しています。現在は009プロジェクト内の .venv のライブラリを使用しますが、009側のアプリやソースは実行しません。別のPCでは下記の初回準備で独立して起動できます。

~~~powershell
.\start-uat.ps1 -Lan
~~~

PCは http://127.0.0.1:8765/ 。スマホは同じWi-Fiへ接続し、起動時に表示される
http://192.168.…:8765/ 等のURLを開きます。スマホ側の127.0.0.1は使いません。
アクセスコードは起動ターミナル、または .runtime/uat-access.html を開いて確認します。
コードは起動ごとに変わります。PCを停止するとアクセスできません。

通常停止は起動したターミナルで Ctrl+C。
バックグラウンド起動時は .runtime/server.json のpidとコマンドがuat_server.pyであることを確認してから、
そのプロセスツリーを停止します。後日古いPIDをそのまま指定しないでください。

別のポートを使う場合：

~~~powershell
.\start-uat.ps1 -Lan -Port 8766
~~~

PCだけで使う場合：

~~~powershell
.\start-uat.ps1
~~~

## 初回操作

1. UATアクセスコードを入力してトラッカーを開く。
2. 従来どおりGoogleログインすると、サマリ／売買記録／分析／新規銘柄判定／設定を利用できる。
3. 判定だけを先に試す場合はログイン画面の「新規銘柄判定を試す（統合UAT）」を開く。売買データは読み込まない。
4. 最初は架空データ。「3時間軸で分析・履歴保存」を押すと上段に要点が表示される。
5. 時間軸、Entry・決算シナリオを選ぶ。採点理由、チャート、根拠、Severe条件と承認は下の詳細を展開。
6. 実銘柄は「銘柄・データ入力」を開き、無料公開日足、CSV・表入力を使用する。
   価格調整基準と確定時刻を確認し、銘柄・出典・Evidence（判断の根拠）を補完する。
7. スクリーンショットはEvidence欄から追加。画像は目視確認して添付し、自動で数値や点数に変換しない。
8. 「実銘柄検証」でテンプレートを取得し、グループ→銘柄入力→独立した人間評価→分析→差分確認を行う。

期限切れの架空データは「履歴」と表示します。買い判定の動作確認のために日付や得点を自動補正しません。
採点上の有用性、支持帯や判断理由の妥当性は、ユーザーの実銘柄UATで確認してください。

## 保存先と将来の売買連携

- 売買記録：従来のFirestore。設定・構造・保存済みデータは変更なし。
- 判定履歴：Windowsの %LOCALAPPDATA%\DaytradePerformanceUAT\history.sqlite。
- 画像：同じ保存先の attachments/。実銘柄比較と承認も専用SQLiteに保存。
- 参照元アプリの履歴DBを自動移行・上書きしない。
- 保存先変更は環境変数 JOURNAL_DATA_DIR。クラウドでは永続ボリューム内を指定する。
- 初回の保存先を .runtime/data-directory.txt に固定し、起動環境の違いで履歴が見えなくなることを防ぐ。実際のパスは .runtime/server.json の data_dir で確認できる。
- 「売買との比較用に判定を保存（JSON）」には analysis_id = run_id、
  銘柄、時間軸、シナリオ、plan_id、分析日時、規則版、元結果を含める。
  trade_id は未接続のためnull。売買記録を自動作成しない。
- 元の売買データを判定・無料Provider・外部AIへ転送しない。
- UATは単一利用者用。アクセスコードを知る端末間で判定履歴を共有する。
  Googleアカウント別の判定履歴分離は外部公開時の課題。

SQLiteをバックアップするときはサーバーを停止して専用保存フォルダ一式をコピーしてください。
稼働中のDBを単純コピーしたり、Google Drive等の同期フォルダを本運用DBに指定しないでください。

## データ接続の区分

|接続|PC・クラウドのブラウザで使用|状態|
|---|---|---|
|無料公開日足、ECB/Fed|可能|ボタン操作による取得、失敗時はCSV・手動補完|
|CSV／画像アップロード|可能|元Windowsファイルパスをサーバーへ渡さず内容をアップロード|
|HYPER SBI 2／kabuステーションAPI|Windows専用の別接続が必要|未接続|
|TradingView専用接続／J-Quants|将来のProvider追加で対応|未接続、契約・認証は未設定|

CSVが価格用か売買履歴用かを区別してください。SBI固有の全CSV形式や画像OCRは未対応です。
無料データだけで財務・需給・材料が揃うとは扱わず、欠損は暫定／評価不能で残します。

## 新しいPC／サーバーで準備

Python 3.13を用意し、正規リポジトリで順に実行します。

~~~powershell
py -3.13 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.lock.txt
.\start-uat.ps1 -Lan
~~~

Linux等では python3.13 -m venv .venv、.venv/bin/python -m pip install -r requirements.lock.txt、
.venv/bin/python uat_server.py を使用できます。公開用ホストの設定・動作確認は未実施です。

## このPCの実行環境

起動スクリプトは -PythonPath 明示指定 → .runtime/python-path.txt → 自前の .venv の順で使用します。
確認済みPython環境へ切り替える場合：

~~~powershell
.\start-uat.ps1 -Lan -PythonPath '確認済み環境のpython.exeのフルパス'
~~~

Windowsの「アプリケーション制御ポリシー」エラー時は、ブロックを解除したり制限を無効にしません。
このPCで別のPython環境を整備する場合は、利用者側で管理方針を確認してください。

## エラー時

- 8765使用中：既存UATを開くか、別Portを指定する。無関係なプロセスは停止しない。
- スマホから開けない：PCと同じWi-Fi、PCの起動、LAN用IP、Windowsのプライベートネットワーク許可を確認。
  この実装ではファイアウォールを自動変更しない。
- Googleログインで auth/unauthorized-domain：既存Firebase側の許可ドメインにそのホストがない。
  Firebase設定を勝手に変更せず、判定だけのUATを進めてから利用ドメインを確認する。
- 判定サーバー接続不可：.runtime/uat-server-error.log と .runtime/decision-server.log を確認。
- CSV不正／評価不能：銘柄、日時、確定足、調整基準、OHLCV、Evidence、Preflightを確認。
- 画面内の一時入力はサーバー再起動で消えるため、入力JSONをダウンロードして保存する。
- 実行テストの一時フォルダは .pytest_tmp を先に作る。計算結果の問題と一時フォルダ不存在を区別する。

## Web公開前に決める事項

現originはPublicリポジトリ。今回指定されたPrivate運用に合わせた確認が必要です。
GitHub Pagesは静的ファイル専用なので、このPython統合版の実行先にはできません。
外部公開するときは、HTTPS、本人認証、永続保存、バックアップ、
Firebaseの許可ドメインを確認します。UATアクセスコードだけでインターネットへ公開しません。
Streamlit Community Cloudを選ぶ場合は、既存静的画面の統合入口と永続保存の設計も必要です。
特定クラウド用のAPIや本番設定への依存は追加していません。
