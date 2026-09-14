# 銘柄判断の本番統合

## 構成と既存機能の保護

既存の静的HTML/JavaScriptトラッカーに通常の［銘柄判断］タブを追加。
iframe、Streamlit画面、UATアクセスコードを本番経路から除外した。
app.jsへの変更は画面名、初期化、タブ表示、認証変更時の消去だけ。
銘柄辞書 stocks.json と既存のGoogleログインを共有する。
サマリ・売買記録・成績分析・設定・Firebase設定・既存取引のデータ構造は変更しない。

判定は app_server.py の /api/judgment/ から investment/src/investment_app の既存処理を呼ぶ。
同梱コードだけで動作し、009プロジェクトのソースを実行時に参照しない。
画面による採点再実装はない。正本17文書、採点config、計算Engineは取り込み元ハッシュと一致。
期限切れ・Critical等の表示保護を presentation.py に切り出し、新旧UIで共有する。

## 起動

このPCでは .runtime/python-path.txt に使用可能なPython環境を設定済み。

~~~powershell
.\start-app.ps1
~~~

[通常アプリ](http://127.0.0.1:8766/) を開き、Googleログインして［銘柄判断］を選ぶ。
認証画面に許可ドメインのエラーが出た場合は、その表示を確認する。
Firebaseの許可ドメイン追加はユーザー確認後に行う。認証回避用の入口はない。

別PC・新サーバーでは Python 3.13 以上の環境を作る。

~~~powershell
py -3.13 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\start-app.ps1 -PythonPath .\.venv\Scripts\python.exe
~~~

このPCではリポジトリ内に新規作成した環境のNumPyがWindowsの実行制御で拒否されたため、
インストール済みで動作する既存Python環境を指定している。ポリシーを緩和しない。
実行環境のパスは .runtime にのみ置き、Gitへ登録しない。
クラウドでは requirements.txt から環境を作り、このPC固有のパスを使用しない。

## 保存

通常アプリはFirestoreへ本人別に分析・画像・承認履歴を保存する。
Python APIは既存Firebase ID Tokenを検証し、検証済みUIDだけを利用する。
本番の正本としてSQLiteやローカルディスクを使用しない。
保存先は users/{uid}/judgmentRuns と judgmentImages。既存取引は変更しない。
旧ローカル履歴の自動移行・削除は行わない。
詳細な公開手順・制限は PRODUCTION_RELEASE.md を参照する。

既存の一意な run_id を分析IDとして利用する。
3時間軸を1トランザクションで追記し、途中失敗時に一部だけ保存しない。
入力・Evidence・規則版・価格プラン・承認対象ハッシュを保持。
比較用JSONには analysis_id / horizon / scenario / plan_id / trade_id:null を含める。
取引への紐付け・実現損益比較は将来機能で、Firestoreへ関連フィールドを勝手に追加しない。

## 本人確認

画面は既存ログインのIDトークンを取得し、Authorizationヘッダーで判定APIへ渡す。
APIはGoogleの [accounts.lookup](https://docs.cloud.google.com/identity-platform/docs/reference/rest/v1/accounts/lookup) で検証する。
JWT本文を読むだけで認証済みとは扱わない。検証成功時のみ短時間キャッシュする。
Firebaseの公開Web設定は既存 app.js から読む。秘密鍵・管理者鍵・新たなAPIキーは不要。
すべての分析・履歴・画像・承認APIで本人確認を行い、本人IDはリクエスト本文から受け取らない。
ログアウト・利用者切替時は画面の入力と結果を消去する。
注文、外部AIへの自動送信、Firestoreの書き換えはこのAPIで行わない。

## 公開とスマホ

スマホ・PCとも同じ通常アプリを開く。画面は390px幅と1440px幅で確認。
上部に結論、表示中の時間軸、推奨時間軸、10点満点の二重スコア、価格、RR、最大懸念、信頼度。
選択欄・詳細・入力は下へ展開する。現在値は最終確定足でありリアルタイム値ではない。

現在のGitHub PagesはPythonを実行できないため、以下のどちらかを選ぶ。

1. 既存Pagesを入口として維持し、Python APIだけをHTTPSで公開する。
2. Python対応のHTTPSサーバーから既存画面とAPIを一緒に提供する。

特定のクラウドSDKには依存しない。Linux等での起動例：

~~~sh
python -m pip install -r requirements.txt
python app_server.py --host 0.0.0.0 --port 8080 --data-dir /persistent/trading-journal --allow-origin https://piro-develop.github.io
~~~

HTTPSは公開先の機能またはリバースプロキシで終端する。
既存Pagesから呼ぶ場合、judgment-config.json の apiBase を
https://<承認済みのAPIホスト>/api/judgment に設定する。
設定先はログイントークンを受け取るため、管理するサーバーだけを指定する。
許可する画面のOriginは --allow-origin で厳密に指定する。ワイルドカードは使用しない。
同じサーバーで画面も公開する場合は既定の /api/judgment のままでよい。
Firebaseの公開設定・許可ドメイン・Pages設定は今回変更しない。

APIへの平文HTTP接続はPC自身の localhost / 127.0.0.1 に限る。
スマホからの実利用にはHTTPSの公開先が必要。
ローカルポートをそのままインターネットへ公開しない。

## 入力と制約

無料日足取得 → CSV → 画像の目視補完の順に利用する。
無料Providerは提供元の制限や停止で取得できない場合がある。その場合はCSVを使う。
日足CSVはUTF-8/CP932と日本語列名に対応。銘柄・調整基準・確定時刻を確認して不足列を補う。
スイングは十分な確定日足・週足、中長期は公式最新財務、デイトレは当日確定5分足と当日材料が必要。

Evidence、独立Preflight、マクロの伝播順、全時間軸の採点カードを通常フォームで補完できる。
詳細JSONは既存の補足形式を維持し、営業日、需給、出来高分布、価値評価式、警告、
支配的材料、Severe解消条件、Evidenceの鮮度・照合情報などに対応する。
外部AIは選択Evidenceの依頼JSONと検証済み応答の手動交換のみ。
画像OCR、全財務・需給の自動取得、リアルタイム板、Windows証券アプリ接続、有料API、自動売買は未実装。

判定表示は既存Engineの出力をそのまま受け取る。
「強気買い」「ブレイク確認」は正本にあるが、参照元の現行Engineには生成分岐がない。
今回、独自の閾値を作ってこれらを生成する変更は加えていない。
現行の買い・条件付き買い・打診買い・押し目待ち・反転確認・見送り、
暫定／評価不能／Severe条件判断を維持する。全ラベル対応の完了とは扱わない。

## 公開前に必要なユーザー操作

- Python APIのHTTPS公開先と永続保存先を決める。
- 既存リポジトリは2026-09-11確認時点でPublic。以前のPrivate運用方針と整合する公開方法を確認する。
- 必要になった場合にのみ、ホストのログイン・Firebase許可ドメイン等を設定する。
- 公開後、実際のGoogleアカウントとスマホでUATを行う。

公開先未確定のため、現在のPagesへのpush・公開設定変更は行っていない。
