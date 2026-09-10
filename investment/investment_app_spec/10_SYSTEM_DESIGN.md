# システム設計 v1.0 — 実装開始前 最終設計版

作成：2026-09-10。対象：正本11仕様書とユーザー確定方針。
本書は実装前の設計成果物。アプリコード・DB・API接続は作成しない。
解消済みの初期運用規則は[11_SPEC_RESOLUTION_PROPOSALS.md](11_SPEC_RESOLUTION_PROPOSALS.md)、採点カードは[13_SCORING_CARDS.md](13_SCORING_CARDS.md)、config契約は[14_INITIAL_CONFIG.md](14_INITIAL_CONFIG.md)、
受入条件は[12_PHASE_ACCEPTANCE_PLAN.md](12_PHASE_ACCEPTANCE_PLAN.md)を参照。

## 1. 要件と設計の対応
| ID | 確定要件 | 設計上の担保 |
|---|---|---|
| R01 | 現在の11文書を正本 | 00〜09とHANDOFFを更新。ユーザー確定方針と設計初期値を区別 |
| R02 | 無料＋手動補完、有料は任意 | Providerの機能宣言と手動入力。未契約を障害にしない |
| R03 | 全時間軸の二重スコア | InvestmentとEntryを別結果・別採点表にする |
| R04 | 週足大局・日足タイミング | Swingの方向特徴量とEntry位置特徴量を分離 |
| R05 | マクロ伝播と強弱比較 | MacroAssessmentに経路とdominant_forceを必須化 |
| R06 | 構造化70＋コンテキスト30 | 項目基準選択→数値写像→固定比率集計。AI自由採点なし |
| R07 | 欠損を0点・見送りにしない | EvaluationStatusをDecisionLabelと分離。欠損はnull |
| R08 | Critical/Severe/Warning | Severe条件判断とユーザー承認。Criticalとの競合、承認失効を管理 |
| R09 | スコアのみで売買しない | Decisionは局面、警告、プラン、材料も必須入力 |
| R10 | 7%未満と条件付き例外 | 未丸めの余地判定＋支配的材料＋合理的RRの独立審査 |
| R11 | 損切先行・第1水準RR | EntryExitの引数に支持帯・無効化根拠。Decisionは価格変更不可 |
| R12 | 決算跨ぎ任意・複数シナリオ | EarningsPolicyとScenarioを別保持 |
| R13 | AI根拠・人間比較 | Evidence参照検証、採用済み評価、HumanReview保存 |
| R14 | 外部送信の除外情報 | ローカルの送信前検査を必須経路にする |
| R15 | 自動売買なし・株数金額なし | 注文インターフェースとPositionSizeモデルを作らない |
| R16 | 時点固定・履歴・事後校正 | AnalysisRun→Snapshot→Decision→ValidationOutcomeの参照 |
| R17 | 結論と価格戦略の1画面表示 | 状態・結論を上段、シナリオ・Evidenceを展開表示 |

## 2. 推奨構成
個人・Windows利用を前提に、一つのPythonアプリの内部を責務分離する。
- UI：Streamlit。入力フォーム、進捗、結果、根拠展開、人間比較画面。
- Application：分析の進行管理、時点固定、再実行、エラー集約。
- Domain：データ型、状態、採点表、価格プラン、例外検査。
- Providers：価格・財務・ニュース／Web・マクロ・CSV・画像の取得。
- 計算：pandas/NumPy等。価格はDecimal相当で扱い、呼値への丸めと得点表示の丸めを区別。
- AI：差し替え可能な一つの接続層。構造化出力の検証、送信前除外処理、実出力保存。
- DB：SQLite。原資料はローカルファイル、ハッシュ・参照先・抽出部分をDBへ保存。
- 初期は外部向けHTTP APIを作らず、型を定めたPython内部関数で接続。公開・複数利用時のみ再検討。

運用DBはPC内の同期対象外領域を推奨。マイドライブへは整合したバックアップを置く。
これはネットワーク／同期領域のロック・競合を避ける設計判断で、現在のマイドライブが破損しているという意味ではない。
DBや保存先の作成は今回行わない。

参考（2026-09-10確認）：
- [Streamlit公式：Pythonサーバーとブラウザ](https://docs.streamlit.io/develop/concepts/architecture/architecture)
- [SQLite公式：ネットワークファイル利用の注意](https://www.sqlite.org/useovernet.html)

### パッケージ案（未作成）
~~~text
app.py
src/
  ui/
  application/
  domain/
  providers/
  normalization/
  engines/
    preflight/
    technical/
    macro/
    scoring/
    entry_exit/
    decision/
  llm/
  persistence/
  validation/
config/
  scoring/
  policies/
tests/
~~~

## 3. 処理順序と依存
1. 入力の銘柄解決、分析時点as_of、時間軸、Entry指定、跨ぎ方針を固定。
2. Providerから取得。失敗・欠損・競合・遅延を明示したデータ束を作る。
3. 初期Preflightで評価不成立の範囲を特定。可能な範囲の処理だけ続行。
4. Technical、Macro、材料整理を実施。新しい欠損・重大材料はPreflightへ追加検査。
5. 構造化評価・コンテキスト評価を基準に沿って作成し、Investmentを集計。
6. EntryExitで支持帯・無効化条件→損切→利確→Entry比較→RRを算出。
7. 各EntryPlanを独立採点。Entry変更はこの段階以降だけを再計算できる。
8. 最終Preflightを含む全入力をDecisionへ渡し、シナリオごとに判断。
9. 結論、全入力参照、採用済み評価、AI実出力、警告、例外、価格を一つの分析履歴として保存。

初期Preflightを通ったことは最終安全性を保証しない。後工程で判明したCriticalも必ず最終結果へ反映。
再取得で新情報を採用するときは新しいデータ束・分析IDにし、途中でデータだけ入れ替えない。
Scoring・Decisionはネットワーク接続やDB書き込みを直接行わない。

## 4. 状態設計
実行状態：queued / running / completed / failed / cancelled。
評価状態：evaluable（評価可能）/ provisional（暫定評価）/ unavailable（評価不能）。
警告重大度：Critical / Severe / Warning。問題なしは空配列で、第四の重大度は作らない。
売買判断：強気買い／買い／条件付き買い／打診買い／押し目待ち／反転確認／ブレイク確認／見送り。
Severe時のAI表示は「Severe警告付き条件判断」。ApprovalRecordを別保存し、ユーザー買い判断をAI判断と分離する。
判断未成立はdecision=null。「未判定」と表示する。評価不能を「見送り」へ変換しない。

評価状態は(symbol, horizon, component, scenario)単位。
componentはinvestment / entry / decision等。警告の適用範囲も同じキーで記録。
例：週足不足はSwing側、前日価格しかないデイトレはDaytrade側の評価を止める。
全体表示では状態を要約するが、正常な時間軸の結果を失わない。
暫定評価の総合点表示条件・必須データ表は11のP02に従う。
Criticalはunavailableを強制。Severeはevaluable/provisionalと併存可能であり、得点へ吸収しない。
データ不十分＋Severeは「評価状態＋Severe警告付き条件判断」。未成立の判断をユーザー承認で成立させない。

## 5. データモデル
IDは安定した文字列。銘柄コードは数値に変換しない。
価格は通貨・調整基準とセット。時刻はタイムゾーンを保持し、表示はJST、日時不明はnull＋理由。
採点可能な0と欠損nullを区別。小数1桁への丸めは表示時だけ。

| モデル | 主なフィールドと関係 |
|---|---|
| Symbol | symbol_id, code, name, market, sector, themes, identifier_sources |
| AnalysisRun | run_id, symbol_id, as_of, request, snapshot_bundle_id, rule_version, model_version, prompt_version, run_status |
| SnapshotBundle | bundle_id, as_of, 各snapshot_id, source_conflicts, content_hash |
| MarketDataSnapshot | id, symbol_id, OHLCV/bars, quote, interval, observed_at, adjustment_basis, is_closed, evidence_ids |
| FinancialSnapshot | id, period, published_at, actual/company_forecast/consensus, metrics, unit, consolidation_scope, evidence_ids |
| NewsEvidence | id, symbol_id, event_id, material_type, event_at, published_at, evidence_ids, supersedes_id |
| MacroSnapshot | id, driver, region, value, unit, observed_at, published_at, evidence_ids |
| TechnicalSnapshot | id, source_snapshot_ids, parameters_version, features, support_resistance_bands, closed_bar_policy |
| Evidence | evidence_id, source_type/name/uri, observed_at/published_at/fetched_at, value/summary, confidence, content_hash, fact_or_interpretation, derived_from, privacy_class |
| PreflightFinding | finding_id, scope, severity, check_type, reason, evidence_ids, checked_at, resolution_condition |
| PreflightResult | scope_statuses, finding_ids, missing_requirements, confidence_components |
| MacroAssessment | sector, sector_condition, drivers, company_sensitivity, specific_factors, dominant_force, horizon, evidence_ids |
| CriterionAssessment | criterion_id, rule_version, anchor_id, evidence_ids, evaluator, rationale, counter_evidence, validation_status |
| ScoringResult | id, run_id, horizon, scenario_id, investment_status, entry_status, structured_score, context_score, investment_score, entry_score, criterion_ids, coverage, missing_ids |
| EarningsPolicy | allow/avoid/unspecified, schedule_date, schedule_status, evidence_ids |
| Scenario | id, run_id, horizon, market_regime, earnings_assumption, entry_assumption, valid_until, invalidation_conditions |
| EntryPlan | plan_id, scenario_id, entry_low/high, reference_entry, target1/2, alert, stop1/2, rr, rr_range, support_ids, invalidation_conditions, status, evidence_ids |
| OverrideRecord | kind, finding_ids, dominant_factor, direction, base_decision, final_decision, reason, why_score_is_insufficient, plan_id, evidence_ids, rr_rationale, reviewed_by |
| DecisionRecord | id, run_id, scenario_id, score_id, plan_id, final_status, base/final_decision, warnings, override_ids, buy/wait_reasons, exit_conditions |
| HumanReview | review_id, run_id, reviewer, independent_assessments, decision, horizon_rank, major_reasons, evidence_ids, difference_categories, adjudication |
| ApprovalRecord | approval_id, run_id, user_id, status, scope, plan_id, finding_ids, target_hash, requested_at, decided_at, expires_at, user_decision, invalidation_reason |
| ValidationOutcome | run_id, plan_id, horizon, evaluation_window, max_gain/loss, target/stop_hits, time_to_hit, same_bar_ambiguity, data_basis |

物理保存の案：symbols、analysis_runs、snapshot_bundles、snapshots、evidence、assessments、
plans、decisions、approvals、human_reviews、validation_outcomes。
型の異なるsnapshotはkindと検証済みJSON payloadを保存し、全モデルを別DBへ分割しない。
検索キー・外部キーは通常列。本文はJSONも許容。外部キー整合とschema_versionを持つ。
一つの完了runの参照をトランザクションで確定する。失敗runは失敗として残し、完成履歴に混在させない。
過去のrunとレビューは上書きせず訂正版参照でつなぐ。削除・保持期間の具体値は運用開始前に設定する。

## 6. 共通インターフェース契約
以下は入出力設計であり実装コードではない。
全結果にscope、status、evidence_ids、findings、rule_version、as_ofを含める。
expected_missingとprovider_errorとinvalid_inputを別分類し、空配列成功で障害を隠さない。
戻り値の数値は単位を必須とし、NaN/無限大を保存しない。
登録されていない規則版・カードIDを指定した場合はrule_not_registeredで正式集計不可。
同一run内でbundle_idが違う結果の混合を拒否する。

| 接続口 | 入力 | 出力 | 禁止・異常時 |
|---|---|---|---|
| MarketProvider.fetch | symbol, start/end, interval, as_of | OHLCV、quote、調整・遅延情報、Evidence | 未契約／空データ／遅延を区別 |
| FinancialProvider.fetch | symbol, periods, as_of | 実績・会社予想・市場予想を区別したsnapshot | 未取得コンセンサスを会社予想へ置換しない |
| NewsProvider.search | symbol, time_window, as_of | 原文参照、発表時刻、検索範囲と未取得情報 | 検索ヒットなしを「悪材料なし」にしない |
| MacroProvider.fetch | driver_ids, time_window, as_of | 単位・観測時刻付き系列 | 全銘柄一律の影響を返さない |
| ImportProvider.parse | local_file, kind, symbol_hint | CSV／画像抽出候補、読取信頼度、行・画像位置 | 元画像の外部送信は別の検査経路必須 |
| Normalizer.build | ProviderResults, as_of | SnapshotBundle、競合・欠損 | 異銘柄、混在調整、未来事実を検出 |
| PreflightEngine.evaluate | Bundle, RequirementPolicy, phase_findings | scope別状態、3段階警告、必要確認 | 得点の加減算をしない |
| TechnicalEngine.compute | market snapshots, horizon, parameters | TechnicalSnapshot | 未来足、高安未確定、必要本数不足を検出 |
| MacroEngine.assess | sector/driver/company Evidence, horizon, criteria | MacroAssessment | 感応度証拠なしなら不明、推測を事実化しない |
| ContextEvaluator.assess | Evidence束, criteria, horizon | CriterionAssessment候補、支配的材料候補 | AIが点数や価格を自由生成できない形式 |
| AssessmentValidator.validate | 候補評価、Evidence、採点表 | 採用可能な基準選択／不足理由 | 不存在ID、時点違反、基準外選択を拒否 |
| ScoringEngine.investment | 採用済み構造化・コンテキスト評価, weights | ScoringResultのInvestment部分 | 欠損再配分・70/30の改変をしない |
| EntryExitEngine.plan | TechnicalSnapshot, Scenario, invalidation_evidence, price_policy | EntryPlan一覧 | 損切のRR逆算、根拠なき目標生成をしない |
| ScoringEngine.entry | EntryPlan, technical/event facts, entry_criteria | プラン別Entry得点 | Investmentへ得点を加算しない |
| DecisionEngine.decide | Preflight, scores, plans, macro, context, exception_policy | DecisionRecord＋承認候補 | Severeだけで見送りにしない。AI単独買い不可 |
| ApprovalService.record | ユーザー明示操作, DecisionRecord, target_hash, now | ApprovalRecord | 対象不一致・失効・Critical・未成立プランを拒否。注文なし |
| HistoryRepository.save | AnalysisRunと全参照結果 | 保存ID、保存状態 | 不完全参照なら完了保存を拒否 |
| ValidationEngine.compare | 凍結run, human review/事後系列 | 差分／ValidationOutcome | 元の判断を変更しない |

Providerはcapabilitiesで項目、履歴期間、更新周期、遅延、調整方式、契約要否を宣言する。
認証・回数制限・一時障害の再試行は取得層に限定。回数上限とタイムアウトを持つ。
過去キャッシュへの切替は日時と理由を表示し、鮮度規則を再適用する。

## 7. 採点とAIの境界
構造化評価 = Σ(w_i × s_i)/100。各s_iは0〜10、構造化配点合計は100。
コンテキスト評価も独自の基準から0〜10へ集計。
Investment = 構造化評価×0.70 + コンテキスト評価×0.30。
Entry = Σ(entry_weight_i × entry_score_i)/100。Investmentへ再混合しない。

数値の閾値比較はプログラム。判断項目はAI／人間がanchor_idを選び、プログラムが点数へ写像。
AIが返す自由なnumberを採点値として受け付けない。理由と該当Evidence引用箇所を必須にする。
コンテキストは構造化の点を再掲せず、持続・反証・作用時期・支配関係を評価する。
Evidence共有は可能だが、同じ特徴量を同じ評価目的で加点しない。criterionごとにpurposeを持つ。
AI解釈は再実行で変わり得る。検証済みの選択・規則・入力を固定した集計再現と区別する。
根拠の妥当性は機械検証だけでは保証できず、人間比較で検証する。

## 8. 価格プラン契約
対象は買い方向の価格戦略。売却は利確・損切・撤退の意味とし、空売り新規ルールは未定義。
有効プランは stop1 < Entry < target1。stop2/target2/Alertは根拠がある場合だけ付与。
stop2 < stop1、target1 <= target2、第1損切 < Alert < Entryを検証する。
丸めで順序が壊れたら無効プラン。第2水準の根拠がない場合はnull＋理由。
RRの目標値を達成するために支持帯・損切を変更しない。
Entry帯の下端・上端ごとにRRを計算。中心価格だけで有利さを示さない。
同じ構造ではtarget1/stop1固定で比較。構造変更は別plan_idにする。
支持抵抗の強度係数・実価格への補正は14。
Entry改善で成立する候補がない場合は「価格プラン未成立」を返し、自由価格を補わない。

## 9. 画面とセキュリティ
入力：銘柄、任意Entry、任意跨ぎ方針、CSV／画像。
上段：時間軸ごとの状態・投資妙味、推奨時間軸、Entry品質、判断、信頼度、Critical/Severe等。
中段：今買う／待つ、跨ぐ／跨がないの比較。Entry・利確・Alert・損切・RR、決算日・残り営業日。
下段展開：買う／待つ理由各3点、支配要因、マクロ伝播、採点内訳、Evidence、撤退条件、履歴、人間評価差分。
未算出値は「未算出：必要な情報」を表示。仮の0を使わない。

外部送信はPrivacyGateを必須とする。公開資料でも口座情報混入があれば送信対象から除外。
画像はPC内で対象部分に切り抜き、外部送信候補を確認できるようにする。
ログ・AI履歴には除外前の秘密情報を残さない。生画像を外部へ送ってマスクさせない。
取得文書の命令文はEvidenceの内容であり、コード実行・権限・送信先の指示として解釈しない。
有料AI接続の金額上限は未指定。接続先・上限決定までは実課金を前提とせず、保存済み／手動評価で開発検証する。

## 10. 最終設計の追加契約
RRの2.0は良好の目標であり足切りではない。1.5以上2.0未満は条件付き、1.5未満は支配的材料がある場合のみ例外。
SevereのAI条件判断とユーザー判断を別に保持。承認の対象ハッシュにはデータ・規則・Evidence・価格・警告・シナリオ・得点を含む。
承認記録は元のDecisionRecordを上書きせず参照でつなぐ。再取得・規則変更・期限超過で失効し、再承認が必要。
分析再表示と承認操作時にも有効性検査を行う。過去の承認は履歴として保存するが現時点の買い承認として表示しない。
型・Evidence存在・構文の検証に加え、根拠の意味は人間比較で確認。人間比較の初期合格条件は14。

## 11. 無料・手動経路のデータ契約
共通手動入力と共通CSV取込を先に用意し、SBI等の固有形式は共通型へ変換するアダプタとする。
価格：symbol_code文字列、timestamp（JSTまたはoffset必須）、interval、open/high/low/close/volume、currency、adjustment_basis、source。
OHLCの大小関係・非負出来高・時系列重複・銘柄一致を検証。欠損値は空として扱い、0へ補完しない。
財務／材料：metricまたはevent、value/summary、unit、period、published_at、source_uri、Evidence位置、fact/interpretation。
採点の手動補完：criterion_id、anchor_id、Evidence、理由、反証。自由な合計点の直接入力は不可。
市場予想未契約でも会社計画・実績・価格反応の許可されたカード経路で評価できるが、足りない項目は未評価とする。
営業日・呼値等の公式表は検証済みの版を入力し、未設定は該当機能を未算出にする。
外部AI未設定時は同じカードを人間が入力できる。実AI比較を完了したとは表示しない。
