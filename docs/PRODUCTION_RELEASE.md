# Render Free / Firestore 公開手順（2026-09-14）

## 公開状態
公開URL: https://piro-develop.github.io/daytrade-performance-app/
公開main: c0d69f0b7001a9dc9e5a71a537dbbe2b4b698b40
復旧タグ: rollback-before-stock-judgment-20260911（変更しない）
Pythonバックエンドは未作成。公開mainは未更新。

## 構成
既存GitHub Pages + Render Free Web Service 1台（Singapore、Docker）。
永続ディスク・有料プラン・管理用秘密鍵は不要。
既存GoogleログインのFirebase ID TokenをGoogleで検証し、検証済みUIDだけを使用。
Firestore RESTにも同じID Tokenを渡し、既存の本人限定ルールを適用する。
既存の取引コレクション、Firebase設定、セキュリティルールは変更しない。

本人の users/{uid}/judgmentRuns/{analysis_id} に分析を保存。
入力・結果・設定を圧縮し、450KB単位のchunks子コレクションへ保存する。
3時間軸の保存は1回のFirestore commitで一括確定する。容量超過は保存前に拒否する。
画像は users/{uid}/judgmentImages/{image_id} 配下へ保存し、上限6MB。
承認履歴も分析の子コレクションへ保存する。
トークンは保存せず、APIリクエスト中だけ使用する。
通常起動ではSQLiteもローカルディスクも使用しない。旧SQLiteコードはオフライン検証用に残す。
旧ローカル履歴の自動移行は行わない。元データは削除しない。

## 無料版の制約
15分アクセスがないとスリープし、次回アクセス時に起動待ちが発生する。
画面は12秒後に待機案内を表示し、180秒で通信を打ち切る。POSTを自動再送しない。
通信失敗時は保存が完了している可能性があるため、履歴確認後に再操作する。
履歴一覧は最新20件。各時間軸を1件として数える。
Firestoreの読み書き・保存容量の無料枠を消費する。既存の請求設定は変更しない。
公式資料:
- https://render.com/docs/free
- https://firebase.google.com/docs/firestore/use-rest-api
- https://firebase.google.com/docs/firestore/quotas

## リリース順序
1. ローカルの保存・主要計算の検証を完了する。秘密情報・個人データを点検する。
2. 正規リポジトリの公開候補ブランチへpushする。Pagesのmainはまだ更新しない。
3. RenderでNew Web Serviceを作り、このリポジトリと候補ブランチを指定する。
4. Docker / Singapore / Free / Health Check: /healthz / Auto Deploy: Off。
   ディスクを追加しない。カード登録・有料契約が求められたら止める。
5. 発行された実URLで scripts/check-production-backend.py を実行する。
6. 既存Googleログインで3時間軸分析、Firestore保存、履歴再表示を実際に確認する。
7. judgment-config.jsonのapiBaseを確認済みHTTPS URL + /api/judgmentへ変更する。
8. mainへpushし、Pagesビルドと公開サイトの既存タブ・銘柄判断を確認する。

## 現在の検証制限
2026-09-14: Windowsのアプリケーション制御がpandasのDLLを拒否し、
主要統合テストは収集時に停止した。合格とは扱わない。
ブラウザー操作ツールも実行環境の起動エラーでRenderへ接続できない。
新構成のRender実起動・実アカウントでのFirestore保存は未検証。
環境を復旧して上記確認を終えるまで公開しない。

## rollback
予行表示:
~~~powershell
.\scripts\rollback-production.ps1
~~~
本番反映後の復旧:
~~~powershell
.\scripts\rollback-production.ps1 -Execute
~~~
旧版へ戻す新commitを通常pushする。Firebaseデータは削除しない。
