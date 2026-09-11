# 公開サイトへのリリース準備（2026-09-11）

## 記録した基準版

- 公開URL：https://piro-develop.github.io/daytrade-performance-app/
- 公開mainとPages成功ビルド：c0d69f0b7001a9dc9e5a71a537dbbe2b4b698b40
- GitHubへpush済みのrollbackタグ：rollback-before-stock-judgment-20260911
- 統合版候補：89e6eed320ea85abf5b1a3a229258211402e8384
- 公開mainは未変更。画面だけ先に公開しない。
- Publicリポジトリの利用は最新ユーザー指示で確認済み。旧Private方針による保留は解除。

## 選定した最小構成

既存GitHub Pages + RenderのWeb Service 1台 + 永続ディスク1GB。
既存Googleログイン、Firestore、公開URLは維持。
Pythonの判定APIだけをHTTPS公開し、本人別SQLiteと画像は /var/data に保存する。

Renderの無料枠は永続ディスクを使えず、現在の保存方法では再配置等で履歴が消える。
このため0.5c-512mbプランと1GBディスクを選定した。
基本料金の目安はサーバー月7米ドル＋保存領域月0.25米ドル＝月7.25米ドル。
税・為替・無料枠超過分は別。無料のHobbyワークスペースを使用し、Pro契約や自動増強は追加しない。
[公式料金](https://render.com/pricing)、[無料枠の制限](https://render.com/docs/free)、[永続ディスク](https://render.com/docs/disks) を確認した。

ローカル通常サーバーの常駐メモリーは約145MB。
本番APIに必要な17パッケージだけを対象にし、Streamlit等のUI用依存を除いた。
Python 3.13/Linux x86_64用の導入ファイルを全件取得できることを確認。
版とハッシュを deploy/requirements-backend.txt に固定した。
このPCにはDocker実行環境がないため、Linuxコンテナー内の実起動はRender作成後に確認する。
不足時に勝手に上位の有料プランへ変更しない。

## 準備ファイル

- render.yaml：シンガポール、1台、512MB、1GBディスク、自動再配置OFF、/healthz
- Dockerfile / .dockerignore：本番APIに必要なファイルだけを取り込む
- deploy/requirements-backend.txt：固定ライブラリとハッシュ
- deploy/production-baseline.json：公開版、候補版、復旧タグ
- scripts/check-production-backend.py：HTTPS・稼働・未認証拒否・Pages通信許可の確認
- scripts/rollback-production.ps1：Gitで旧版へ戻すためのスクリプト

Dockerの公開先はAPIとして使用し、別のユーザー向け画面は追加しない。
新しい秘密鍵・認証トークンはファイルへ書かない。
既存Firebaseの公開Web設定は既存app.jsから読む。Firestoreの設定・ルール・データは変更しない。

## 停止しているユーザー操作

Renderへのログイン（未登録なら新規アカウント作成）、
この有料構成の承認、および必要な支払い設定。
ユーザーの指示どおり、契約・決済操作の前で停止する。
準備ファイルの作成は有料サービス作成の承認を意味しない。
公開バックエンドの実URLはまだ発行されていない。

## 操作後のリリース順序

1. 秘密情報・個人データを含めないことを確認し、正規リポジトリの検証用ブランチへ候補をpushする。Pagesのmainは変更しない。
2. RenderのGitHub連携をこのリポジトリに限定し、検証用ブランチを指定する。
3. render.yamlの1サービス・1ディスクを確認して作成。料金はユーザー自身が確認する。
4. Render発行の実際のHTTPS URLを確認し、推測したURLは使用しない。
5. HTTPS、稼働、未認証拒否、Pagesからの通信許可、既存Googleログイン、
   3時間軸分析、履歴再表示、再起動後も保存データが残ることを確認する。
6. judgment-config.json の apiBase を、確認したHTTPS URL + /api/judgment に設定する。
7. 公開mainが基準SHAから変わっていないことを確認して、統合版をmainへpushする。
8. Pagesのビルド完了後、公開URLで既存タブと［銘柄判断］の実分析を確認する。

ログインが必要な場合はユーザー自身が操作する。トークンをチャットに貼らせない。
APIキー・認証トークン・個人データ・分析DB・画像・.runtime は追加pushしない。
手順5が完了するまで本番mainを更新しない。

## 即時rollback

まず予行表示：

~~~powershell
.\scripts\rollback-production.ps1
~~~

本番反映後に旧版へ戻す：

~~~powershell
.\scripts\rollback-production.ps1 -Execute
~~~

作業ツリーが空で、ローカルmainと公開mainが一致する場合だけ実行する。
記録したタグを検証し、旧版のファイルへ戻す新commitを作って通常pushする。
force-push、reset --hard、git clean、DB削除は行わない。
Pagesビルド完了後に旧画面を確認する。Firebaseと分析DBは維持する。
APIは自動再配置OFFなので、mainのrollbackで分析サーバーを自動更新しない。

復旧スクリプト自身は旧版にないため、復旧後にリポジトリからなくなる。
基準SHAとタグはGitHubに残る。実行前の予行表示は確認済み。
