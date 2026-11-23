# codex-auto-resume

macOS で登録した Codex CLI の会話を監視し、最新ターンに利用上限エラーが記録され、対象枠が回復したとき、元の作業ディレクトリから同じ会話に一度だけ続きを依頼します。ログインユーザーの LaunchAgent が動くので、登録したターミナルは閉じられます。

**実機で確認できた範囲**（2026-11-23）　macOS 27.2.1、Python 3.9.6、Codex CLI 0.171.0、ChatGPT アカウント認証で、別プロセスから指定会話の最新ターンと利用枠を照会できました。確認した会話の8ターンはいずれも `completed` で、対象枠は `codex` でした。この版が自然な上限停止の失敗理由を履歴に残すかは未確認です。実アカウントでの回復後の送信、非対話実行時の承認の扱い、スリープ・再ログインをまたぐ動作も実地確認が残っています。

## 導入と登録

ChatGPT アカウントでログインした `codex` と Python 3.9 以降を用意し、このリポジトリのルートで実行します。登録後もインストール先と Python・Codex の実行パスを維持してください。

```sh
mkdir -p "$HOME/.local/bin"
install -m 755 bin/codex-auto-resume "$HOME/.local/bin/codex-auto-resume"
export PATH="$HOME/.local/bin:$PATH"
```

端末で起動すると、スクリプト先頭の `#!/usr/bin/env python3` がその時点の PATH にある Python 3 を選びます。使うのは Python の標準ライブラリだけです。`watch` は使った Python、スクリプト、Codex CLI の絶対パスを記録し、ユーザー単位の LaunchAgent を登録して終了します。

以降は macOS の `launchd` が登録時・ログイン時と約60秒ごとに、記録した Python で `codex-auto-resume _tick SESSION_ID` を起動します。通常は1回確認して終了し、待機期限前ならローカルの状態を読むだけです。回復を確認すると、元の作業ディレクトリで `codex exec resume` を起動し、その終了結果を記録します。

対象の対話型 Codex で `/status` を開き、セッション ID をコピーします。次の `SESSION_ID` はその UUID に置き換えてください。

```sh
codex-auto-resume probe SESSION_ID
codex-auto-resume watch SESSION_ID
codex-auto-resume status SESSION_ID
codex-auto-resume cancel SESSION_ID
```

`probe` は読み取り専用です。自然に上限で止まった直後、次のターンを送る前に実行し、**上限停止ターンの ID** と対象の利用枠が表示されるかを確認できます。失敗が保存されない版では既存会話の停止を検知できません。代替方式の設計案はツールから会話を開始し、その App Server の実行中の通知を購読するものです。[設計書](docs/design.md)

`watch` は上限停止の前後どちらでも登録できます。複数枠がある場合は、対象モデルの枠を確認して `watch SESSION_ID --bucket LIMIT_ID` と指定してください。`probe` にも同じ指定ができます。有効な予約への再登録は現在の状態を表示します。終端状態の結果を確認し、次の停止に備えるには `watch SESSION_ID --new` を使います。送信試行済みの同じ失敗ターンは再送しません。

## 状態の読み方

| status の表示 | 動作と確認先 |
| --- | --- |
| `watching` | 約60秒ごとに最新ターンを確認します。通常終了や手動中断後も監視を続けます。 |
| `waiting` | 失敗ターンを記録しました。対象枠・理由・現地時刻の次回確認予定を表示します。複数の窓を使い切った場合は最も遅い既知のリセットまで待ち、期限後に利用率と通常枠で実行可能かを再照会します。 |
| `dispatching` | 登録時のディレクトリから UUID と固定メッセージを指定して再開を試行しています。`cancel` はこの状態を表示します。 |
| `done` | 再開用 CLI が正常終了しました。依頼の進捗と承認の要否は元の会話で確認してください。 |
| `cancelled` | 利用者が解除したか、新しいターンを観測しました。 |
| `needs_attention` | 理由に応じてログイン状態・利用枠・作業ディレクトリ・会話履歴を確認してください。送信結果が不明なときは再送を止めます。LaunchAgent 登録失敗は `watch` で再試行できます。 |

通信障害やリセット時刻不明の場合は1、2、4、8、最大15分間隔で照会します。ログイン中のスリープから復帰したとき、または次回ログインで監視が起動したときに、保存済みの期限を再評価します。自動送信の直前にも最新ターンを確認します。別の Codex からの手動送信がその最終確認と CLI 起動の間に入る競合は残ります。

再開コマンドは `codex exec resume SESSION_ID PROMPT` です。既存設定を使い、プロジェクト信頼・サンドボックス・承認を変更するオプションは渡しません。シェルコマンドの途中状態は復元されません。支出上限・クレジット枯渇時は利用者の確認が必要です。

## 記録とアンインストール

状態・ロック・遷移ログは `~/Library/Application Support/codex-auto-resume/SESSION_ID/` に所有者限定で保存します。CLI の標準出力・標準エラーや会話本文は保存しません。セッション単位の plist は `~/Library/LaunchAgents/local.codex-auto-resume.SESSION_ID.plist` に配置し、終端状態で解除します。

アンインストールするには、履歴ディレクトリの各 UUID に対して `codex-auto-resume cancel SESSION_ID` を実行してください。`dispatching` は元の会話と `status` で終了を確認してから、実行ファイルを削除します。

```sh
rm "$HOME/.local/bin/codex-auto-resume"
```

履歴も削除したい場合は、Finder の「フォルダへ移動」で `~/Library/Application Support/codex-auto-resume/` を開き、不要なセッションのディレクトリを削除してください。

## 開発と検証

`python3 -I scripts/check.py` で、追跡ファイルの認証情報パターン、シェル経由の起動、模擬 RPC と予約状態のテストを検査します。pre-commit がインストール済みなら次を実行してください。GitHub Actions は push・PR 時に macOS 上で同じ検査を実行します。

```sh
pre-commit install
pre-commit run --all-files
```

ログイン中の Mac では `python3 -I scripts/smoke-launchd.py` で、空の一時 HOME への配布、実際の LaunchAgent の登録・自動起動、模擬 Codex への一回送信、終端時と手動での解除を再現できます。上記の実機環境でこの検証を実施しました。CI の Codex と launchctl はどちらも模擬実装です。
