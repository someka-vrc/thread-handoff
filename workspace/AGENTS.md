# 作業の進め方

- 始めるとき `/kickoff <thread-id>`、区切りで `/sync`、終えるときと話題が変わるときは `/handoff`。誤りの指摘を受けたら `/internal-review`。
- **STATE.jsonl は毎回守る**: 新しい指示・決定・完了・方針転換があったら、返答の前に STATE.jsonl を更新する（変化がなければ何もしない）。
- STATE.jsonl とログに書く値は**1行に収め**（改行を入れない）、パスは **`/` 区切り**で書く（`\` は使わない）、引用符は「」を使う。エスケープでコマンドが壊れるため。
- 方針や状況を覚えておきたくなったら、STATE.jsonl の note に書く（`until` か `promote` を付ける）。ログと HUMAN.md は sync / handoff でまとめて書いてよい。
