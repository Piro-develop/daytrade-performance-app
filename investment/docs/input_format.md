# 入力形式
## 最短の確認
「テストデータ」を選び「分析する」。架空データのため、実銘柄への転用時は必ず全内容を置き換えてください。

## 日足CSV
UTF-8、1銘柄、完成した日足のみ。必須列：
`symbol_code,timestamp,open,high,low,close,volume,adjustment_basis`

|列|意味|
|---|---|
|symbol_code|文字列の銘柄コード。入力画面と補足情報と一致|
|timestamp|日足の確定日時。例2026-09-09T15:30:00+09:00|
|open/high/low/close|始値/高値/安値/終値。正の有限値|
|volume|その完成日の出来高。0以上。欠損は空欄|
|adjustment_basis|同じ価格調整基準。例split_adjusted|

初期入力は日本株の日足・円価格に限定しています。分足、外貨、未完成の日足をこの形式に混入させないでください。
元データを日足に見せる変換はしません。欠損OHLCV・未来価格・銘柄不一致は入力エラーです。
同時刻に異なる価格があればCriticalで評価不能。同一行の重複は警告して除去します。
通常、週線の採点には58確定週足以上の日足が必要です。156週は探索上限で、必須本数ではありません。

## 補足JSON
画面でアップロード、または「入力形式・手動補完」内のJSON欄を編集できます。
`data/demo_evidence.json` に全項目の例があります。単なるコード入力だけでは価格・財務は取得しません。
補足未入力は正常な不足状態として扱い、架空値を埋めません。

|項目|内容|
|---|---|
|symbol/name|銘柄コード・表示名|
|evidence|出所・本文抜粋・日時・ハッシュを持つ根拠配列|
|assessments|カードごとのアンカー選択。合計点は入力不可|
|preflight_review|negative_news/thesis/liquidityの独立確認|
|tick_size/tick_evidence_id|検証済み呼値と根拠ID。未設定なら正確な価格プランは評価不能|
|calendar|YYYY-MM-DDの実取引日一覧。分析時点・次の営業日・決算日までの範囲|
|calendar_note|利用した取引カレンダーの出所・版|
|earnings_at/earnings_evidence_ids|次回決算日時と根拠ID。不明なら省略|
|macro|セクター・ドライバー・企業感応度・個別比較|
|warnings|重大度、対象、根拠、理由、解消条件|
|severe_conditions|警告コード別の条件判断理由・残るリスク・解消条件・Evidence|
|dominant_factor|支配的材料。方向、作用、反証、失効条件を説明|
|volume_profile|実測の価格帯low/high、volume、measured、根拠ID|
|exit_conditions|価格と無関係な撤退条件の配列|
|evidence_quality|Evidenceごとの鮮度・出所・独立照合の確認|

カレンダー未入力では営業日数は未算出、週の確定は金曜15:30を保守的な基準にします。
架空カレンダーは祝日を含む実取引カレンダーではありません。
公開時刻が不明な決算を引け後と推測して入力しないでください。この試用版では日付だけの決算登録UIは未対応です。

### Evidence
必須：evidence_id、source_name、source_uri、observed_at、published_at、fetched_at、summary、content_hash。
日時には時差を付けます。summaryには確認した事実と原資料のページ・表・該当箇所を記載してください。
fact_or_interpretationはfact/interpretation/hypothesisで事実と解釈を分けます。
derived_fromで派生元をつなぎます。未来の公表内容を過去時点の評価へ入れることは拒否します。
元の資料自体は出所を保持してください。DBは入力抜粋を保存し、URL先の全内容は自動保存しません。

### 採点
criterion_id、anchor（1/4/6/8/10）、rule_version（cards-1.0.0）、evidence_ids、
reason、counter_reason、evaluator（human）を指定します。
同じ資料を複数カードに使う場合でも、reasonにはそのカード固有の作用を説明します。
カード一覧と各段階の意味は `config/scoring_cards.json` と正本13。
規則外の値、根拠なし、反証なし、重複カード、旧版規則は未評価。不存在カードIDは入力エラーです。

SW-D1（週線方向）、SW-D2（週足高安）、SE-A〜Fはプログラムが計算し、手動得点で上書きしません。
そのほかの財務・材料・需給・比較・コンテキスト・SE-Gは、この段階では根拠付き手動カードです。
将来のAIも同じ基準選択とEvidence検査を通す設計で、計算可能な価格・指標・RRを推測させません。

### 鮮度・信頼度
evidence_qualityのキーはEvidence IDです。valid_untilで原資料の有効性確認期限、
source_qualityでoriginal_verified（原資料確認済み）／secondary_verified／image_verifiedを入力します。
期限内でも遅延制約があればconstrained=true。独立資料の照合はindependent_evidence_idsとmatch_reasonを保存します。
未照合はX=0.5、未取得は0。照合元が同じ原系列なら独立資料として申告しないでください。
必要な資料の鮮度が未確認・期限外なら、合計が算出できても暫定評価として正式な買いを出しません。
confidentialな口座情報・APIキー・残高などを補足情報へ入力しないでください。外部送信機能はありません。

### 支配的材料
direction=positive/negative、reason、why_score_is_insufficient、invalidation、evidence_idsを必須とします。
7%未満／RR1.5未満の買い例外ではrr_rationale、alternative_entry_reasonも必須です。
alternative_entry_reasonには代替Entryと、その場合の取り逃しリスクを説明します。
これらを埋めてもCriticalや未成立プランを解除できません。

## 画面の承認
Severeは警告付き条件判断として表示します。必要根拠・買い条件・有効期限を満たすと本人が承認できます。
承認対象のデータ・Entry・規則・警告・シナリオが変わると承認を再利用できません。
履歴画面と架空テストデータは参照専用。承認・拒否は元の分析と別に保存され、注文は発生しません。
