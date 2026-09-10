# UAT開始版の操作案内

この版は機能を操作して確認する版です。投資判断としての有用性・精度はユーザーUATで確認します。実銘柄5〜10銘柄の内部検証は実施していません。

## 起動と最初の操作
このプロジェクトのフォルダをPowerShellで開きます。

~~~powershell
.\.venv\Scripts\python.exe -m streamlit run app.py
~~~

http://127.0.0.1:8501/ を開き、「3時間軸で分析・履歴保存」を押します。
最初は架空TEST0001、固定日時の開発データです。期限切れ表示は仕様どおりです。
既に起動している場合はブラウザを再読込するだけで使えます。
8501が使用中と表示されたら、既存の画面を利用し、二重起動を避けてください。

上段：時間軸候補、最終判断、投資妙味、Entry品質、現在値、Entry、利確・損切、Alert、RR、信頼度。
下段：「詳しく確認する時間軸」を選び、理由、価格候補、撤退条件、決算、チャート、採点内訳とEvidenceを開きます。
期限切れの結果は履歴として表示し、現在の推奨Entryにはしません。

## 実データを入れるとき
1. 「銘柄・データ入力」で銘柄コード、分析日時、CSVまたは無料公開日足を選びます。
2. データの調整基準、対象期間の確定時刻を原資料で確認し、「入力を読み込む」を押します。
3. Evidence表へ出典・該当箇所の要約・情報日時・公表日時・取得日時・有効期限を記入します。
4. 採点カードの時間軸を選び、定義済みアンカー、Evidence ID、理由と主要反証を入力します。「編集した入力を保持」で時間軸間の編集を保持できます。
5. Preflight、呼値、決算、企業・マクロ経路を補完して分析します。
6. 入力はJSON、結果もJSONで書き出せます。分析履歴は自動保存します。

日足CSV列：symbol_code,timestamp,open,high,low,close,volume,adjustment_basis。
日時例：2026-09-09T15:30:00+09:00。日本語列名、UTF-8/CP932も読み込めます。
OHLCは始値・高値・安値・終値です。欠損値を0にしません。
日付のみの場合、指定する確定時刻が対象期間全体に適合することを確認してください。
中長期は確定週足58本・確定月足24本を作れる履歴が必要です。約3年以上を目安に用意します。
分割等の前後で未調整価格を混ぜたまま、価格構造を評価しないでください。

デイトレCSV：timestamp,open,high,low,close,volume。timestampはJST等の時差を持つ確定5分足の終了時刻。
当日材料・分足・累積出来高の同時刻比較にそれぞれEvidenceが必要です。
板がなくても入力できますが、約定環境を確認していない高い執行評価は採用しません。
15分超遅延は暫定、当日分足がなければ評価不能。引け後は振り返りです。

## 必要な補足情報
- 原資料：最新の企業IR、業績・会社計画、材料・予定、需給、比較銘柄・指数、セクター情報。
- 呼値：この銘柄に適用する値と確認資料。
- 決算：日時と根拠。跨ぐ方針が未指定なら両シナリオを表示します。
- マクロ：セクター→地合い→主要ドライバー→企業感応度→個別要因との強弱比較。
- Preflight：重大悪材料、投資前提、流動性を独立確認。警告をCritical/Severe/Warningで記入。
- スクリーンショット：銘柄・数値・日時を目視確認して根拠へ追加できます。自動OCRはありません。
- 中長期ME-E：RRに加え、ストレス下落の根拠付きアンカーが必要です。
- 信頼度：Evidence表のsource_qualityはoriginal_verified / secondary_verified / image_verified / unknown。有効期限が未確認なら鮮度を高く見積もりません。

不足は「未評価」「暫定評価」「評価不能」として表示します。全カードを埋めるために架空値を入れないでください。
詳細補足JSONではSevere例外の根拠、支配的材料、取引カレンダー、実測出来高分布、評価レンジを登録できます。
[data/uat_input_template.json](../data/uat_input_template.json)は空のひな形です。

## 中長期の代替利確レンジ
週・月足の有力抵抗が得られない場合だけ、根拠付きEPS×適合PERを代替に使えます。
valuation_planにformula="EPS*PE"、currency="JPY"、eps、multiple_first、multiple_final（任意）、
period、assumptions、sector_suitable_confirmed=true、evidence_idsを指定します。
赤字にPER式は使いません。損切は実支持から決定します。代替使用はWarningと計算Evidenceに残ります。

## 無料データとAI
- 無料日足：Stooq公開CSV用Provider。取得先の仕様変更・制限等で取得できない場合はCSVを使用します。調整基準は確認が必要です。
- 為替：ECB公式参考レート。EUR基準値と、JPY/EUR ÷ USD/EURでプログラム計算したUSDJPYを取得。売買のリアルタイム価格ではありません。
- ニュース：Federal Reserve公式金融政策RSS。取得情報をEvidence候補から選択して追加します。
- 原油・その他商品、国内外指数、企業IR・財務・地政学等は、出典付きEvidenceとマクロ経路へ手動登録できます。
- AI：公開・分析用Evidenceを選択して依頼JSONを出力し、応答JSONを検査して取り込めます。SC/MC/DCの定性コンテキストに限定します。
- AIの自由点数、価格・計算項目、未知のEvidence、根拠にない説明中の数値は拒否します。
- 外部AIへの自動送信、有料Provider、リアルタイム価格・板取得、IR/財務の全面自動取得は未接続です。基本UATにキーや登録は不要です。

参考：[ECB公式データ](https://www.ecb.europa.eu/stats/policy_and_exchange_rates/euro_reference_exchange_rates/html/index.en.html)、
[Federal Reserve RSS](https://www.federalreserve.gov/feeds/feeds.htm)、
[JPXの適時開示閲覧](https://www.jpx.co.jp/listing/disclosure/01.html)。
JPX閲覧ページは自動スクレイピングを控える案内があるため、直接閲覧・手動補完にしています。

## 保存と確認
履歴と画像：%LOCALAPPDATA%\InvestmentDecisionSwing\
既存の検証機能：/?workspace=validation
従来のスイング画面：/?workspace=legacy
ユーザーデータを初期化する処理、注文、株数・投資金額計算はありません。

UATでは、時間軸の使い分け、買う／待つ理由、実支持に基づく価格と撤退条件、不足情報の分かりやすさ、
Evidence追跡、Severe承認、保存後の再表示を中心に確認してください。
実銘柄検証機能の人間評価・6分類の差分記録は引き続き利用できます。
