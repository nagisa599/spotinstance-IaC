# koita-ai-v2

論文原稿を添削するスキル（paper-review）．
信学技報，IEEE論文・国際会議，大会原稿，卒論・修論の原稿を，体裁から主張の強さまで決まった順で確認し，変更前／変更後の表で指摘を返す．
指摘の理由には，根拠とする書籍・資料（『理科系の作文技術』，電子情報通信学会編『学術論文の書き方・発表の仕方』，通信ソサイエティマガジンの「論文の書き方講座」など）のページを示す．

中身は `skills/paper-review/SKILL.md` にある．

koita-ai-v1（小板として話すスキル）とは別のスキルで，併用できる．

## 入れ方

### Claude Code

このフォルダごと手元に置き，起動時に指定する．

```
claude --plugin-dir /path/to/koita-ai-v2
```

スキルだけ使うなら，`skills/paper-review/` を `~/.claude/skills/` に置く（`~/.claude/skills/paper-review/SKILL.md` になる形）．

### claude.ai（Web，デスクトップ）

`skills/paper-review/` フォルダを zip にする（フォルダが zip の根に来る形）．
Customize > Skills で「+」，「Create skill」，「Upload a skill」の順に進んで上げ，一覧でオンにする．

## 使い方

原稿のPDF・Word・LaTeXを渡して，「原稿見て」「投稿前にチェックして」と頼む．
最優先で直すべき指摘が3〜5件，続いて確認項目ごとの指摘が表で返る．
