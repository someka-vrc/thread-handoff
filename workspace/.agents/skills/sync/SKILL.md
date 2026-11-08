---
name: sync
description: 作業の途中経過を記録する軽量版。会話の現状を STATE.jsonl に反映し、未記録の決定をログに足し、人間待ちを HUMAN.md に足す。「sync」「記録して」と言われたときや、区切り（タスクが終わった・方針が変わった・会話が長くなった）に使う。読み込みは該当行だけで、セッションは閉じない（閉じるときは handoff）。
---

# sync

途中経過をスレッドのファイルに書き出す。kickoff（全部読む）や handoff（閉じる）と違い、**読み込みを最小にして書くだけ**。対象は今のスレッド（`_ops/threads/<thread-id>/`）。今のスレッドが分からなければ、`grep -H '"type":"meta"' _ops/threads/*/*-STATE.jsonl` の一覧を見せて尋ねる（推測で書かない）。

## 1. STATE.jsonl を現状に合わせる

- 全文は読まない。更新する行は ID で grep して、その行だけ Edit する。
  `grep -n '"id":"002"' _ops/threads/<thread-id>/<thread-id>-STATE.jsonl`
- ユーザーが STATE.jsonl を直接編集したと言ったときだけ、全文を読み直す（古い内容で上書きしない）。
- 会話で起きたことを反映する:
  - 終わった task → 行ごと消す（その ID を `dependsOn` に持つ行はそのままでよい）
  - 進んだ・止まった・分かった → `status` / `waitingOn` / `detail` を直す
  - 新しい task・指示 → 最大ID+1 で末尾に足す（今やるなら `doing`、後でやるなら `next` / `later`）
  - タスク横断の進め方・状況 → note（`until` か `promote` を必ず付ける）
- 書式は既存の行と同じにする（キー順・子は1階層まで・孫は作らない・値は1行・パスは `/` 区切り・引用符は「」）。task の行は次の形（必須は先頭の3つ。`waitingOn` は `human` か `client`）。
  `{"id":"003","status":"next","title":"…","detail":"…","dependsOn":["002"],"waitingOn":"human","refs":["_ops/threads/<thread-id>/work/<目的>/memo.md"]}`

## 2. 未記録の決定をログに足す

このセッションで決めたことのうち、まだ `-log.jsonl` に無いもの（ユーザーと決めた仕様・採用しなかった案・ハマりどころ）を、シェルの `>>` で1行ずつ足す。過去の行は書き換えない。単純なコミット・プッシュ・マージは書かない（判断を伴ったときは、その判断を書く）。

`{"date":"2026-11-07","title":"…","decision":"何を決めた・何をした","why":"理由","by":"user|ai","files":["…"]}`

- `by`: ユーザーが決めた・指示したなら `user`、AIが推測・判断したなら `ai`。`files` は任意。
- 値は1行に収める（改行を入れない。`\n` も使わない）。パスは `/` 区切りで書き、`\` は使わない。長くなる内容は `_ops/threads/<thread-id>/work/<目的>/` にメモを置き、`files` で指す。追記は `>>` のシェル経由なので、改行と `\` がエスケープ事故の元になる。
- 値の中の引用符は「」を使い、ダブルクォートや `'` は避ける。どうしても必要なときは、次のように書く。

```bash
# 一番安全: ヒアドキュメント。シェルのエスケープは要らず、JSON のダブルクォートだけ \" と書く
cat >> _ops/threads/<thread-id>/<thread-id>-log.jsonl <<'EOF'
{"date":"2026-11-07","title":"it's","decision":"say \"hi\"","why":"理由","by":"ai"}
EOF

# 1行で書く場合: 全体を ' で囲み、値の中の ' は '\'' と書く
printf '%s\n' '{"date":"2026-11-07","title":"it'\''s","decision":"say \"hi\"","why":"理由","by":"ai"}' >> _ops/threads/<thread-id>/<thread-id>-log.jsonl
```

```powershell
# 全体を ' で囲み、値の中の ' は '' と書く。JSON のダブルクォートは \" と書く。ダブルクォートで全体を囲むと $ や ` が展開されるので使わない
Add-Content -Encoding utf8 -LiteralPath '_ops/threads/<thread-id>/<thread-id>-log.jsonl' -Value '{"date":"2026-11-07","title":"it''s","decision":"say \"hi\"","why":"理由","by":"ai"}'
```

## 3. 人間にしかできないこと

`waitingOn` が `human` の task が増えていたら、`-HUMAN.md` にチェックボックスで足す。済んだもの（チェック済み・消されたもの）は消す。

## 4. 報告

何を直したかを1〜2行で伝える（例: 「STATE: 003 を消し、005 を足した。ログ1件」）。変更が無ければ「変更なし」と言う。
