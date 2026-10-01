#!/usr/bin/env python3
"""
new.py — 新規タスク／課題の md 雛形を open/ に作成する

Usage（詳しくは python3 new.py -h。-h は何も作らない）:
  python3 new.py <area> "タイトル" [--kind 課題] [--priority 高] [--owner 名前] [--due YYYY-MM-DD]
                 [--decider SH-02] [--tag タグ ...] [--add-area 名前:PREFIX]
  python3 new.py <area> "問いの形の題" --decided "決定内容" --to "反映済: 01 §3" [--to APP-03]

例:
  python3 new.py 横断 "ログイン画面のバリデーション追加" --due 2026-10-07
  python3 new.py 運用 "バックアップを何世代残すか" --kind 課題 --decider SH-02
  python3 new.py 横断 "対象範囲をどこまでにするか" --decided "本社の正社員のみ" --to "反映済: 01 §3"

分類（kind）: タスク（既定）＝実行して完了させる作業／課題＝意思決定・すり合わせが
必要な未決事項（未決の正本。決着したら `## 決定` を書いて close.py でクローズ）。

出力の 1 行目は確定した ID だけ。打合せ記録・落ち先にはこの ID を写す（起票前に予想して書かない）。
領域 → プレフィックスの対応表は同じフォルダの areas.json が唯一の正本。
未登録の area は止まる（exit 2）。登録済みのプレフィックス（APP・qa など）は名前に読み替える。
引数の誤りはすべて exit 2 で、何も作らない。
"""
import argparse
import datetime
import json
import re
import subprocess
import sys
from pathlib import Path

BASE_DIR = Path(__file__).parent
OPEN_DIR = BASE_DIR / "open"
CLOSED_DIR = BASE_DIR / "closed"
AREAS_JSON = BASE_DIR / "areas.json"
ROOT = BASE_DIR.parent.parent.parent          # docs/案件/01_タスク管理 → 案件ルート
HOOKS_DIR = ROOT / ".claude" / "hooks"

KINDS = ("タスク", "課題")
PRIORITIES = ("最高", "高", "中", "低")
PREFIX_RE = re.compile(r"[A-Z][A-Z0-9]*")
# タスク・課題以外の ID に使っている接頭辞（ロール・ADR・ハーネス・原則・不変条件・画面・旧未決）
RESERVED_PREFIXES = {"SH", "ADR", "HN", "P", "INV", "SCR", "U"}


def die(msg: str, code: int = 2) -> None:
    print(f"エラー: {msg}", file=sys.stderr)
    sys.exit(code)


def note(msg: str) -> None:
    """補足は stderr に出す（stdout の 1 行目は ID だけにする）。"""
    print(msg, file=sys.stderr)


# ---------------------------------------------------------------------------
# 領域（areas.json）
# ---------------------------------------------------------------------------

def load_areas_data() -> dict:
    """areas.json 全体を読む。無い・壊れているときは空の形を返し、理由を stderr に出す。"""
    if not AREAS_JSON.exists():
        note(f"警告: {AREAS_JSON.name} が見つかりません（--add-area で作るか、手で置く）")
        return {"areas": {}}
    try:
        data = json.loads(AREAS_JSON.read_text(encoding="utf-8"))
        if not isinstance(data, dict) or not isinstance(data.get("areas", {}), dict):
            raise ValueError("'areas' が辞書ではありません")
        data.setdefault("areas", {})
        return data
    except (OSError, ValueError) as e:
        note(f"警告: {AREAS_JSON.name} を読めません: {e}")
        return {"areas": {}}


def area_list_text(areas: dict[str, str]) -> str:
    if not areas:
        return "（なし）"
    return "、".join(f"{k}={v}" for k, v in areas.items())


def parse_add_area(spec: str, areas: dict[str, str]) -> tuple[str, str]:
    """`名前:PREFIX` を検証して (名前, PREFIX) を返す。`PREFIX:名前`（init.py --areas の順）も読み替える。"""
    parts = re.split(r"[:：]", spec, maxsplit=1)
    if len(parts) != 2:
        die(f"--add-area の書式が不正です: {spec!r}（名前:PREFIX の形。例: --add-area 仕様:SPEC）")
    name, prefix = parts[0].strip(), parts[1].strip()
    if not PREFIX_RE.fullmatch(prefix) and PREFIX_RE.fullmatch(name):
        name, prefix = prefix, name                     # PREFIX:名前 の順で書かれた
    if not name:
        die(f"--add-area の領域名が空です: {spec!r}")
    if not PREFIX_RE.fullmatch(prefix):
        die(f"--add-area のプレフィックスは大文字英数字（先頭は英字）にしてください: {prefix!r}")
    if prefix in RESERVED_PREFIXES:
        die(f"プレフィックス {prefix} は ID 体系で予約済みです（{'・'.join(sorted(RESERVED_PREFIXES))} は使わない）")
    if name in areas:
        die(f"領域 {name!r} は既に登録済みです（{areas[name]}）。--add-area を外して再実行する")
    used = {v.upper(): k for k, v in areas.items()}
    if prefix in used:
        die(f"プレフィックス {prefix} は既に領域 {used[prefix]!r} で使われています")
    return name, prefix


def resolve_area(area: str, areas: dict[str, str]) -> str:
    """登録済みの名前ならそのまま。登録済みのプレフィックスなら名前に読み替える。未登録は exit 2。"""
    if area in areas:
        return area
    by_prefix = {v.upper(): k for k, v in areas.items()}
    name = by_prefix.get(area.strip().upper())
    if name:
        note(f"area は {name} として扱います（{area} は {name} のプレフィックス）")
        return name
    die(
        f"area {area!r} は未登録です。\n"
        f"  登録済み（名前=プレフィックス）: {area_list_text(areas)}\n"
        f"  新しい領域なら --add-area 名前:PREFIX を付けて再実行するか、{AREAS_JSON.name} に足す"
    )
    return ""  # 到達しない


# ---------------------------------------------------------------------------
# 採番・雛形
# ---------------------------------------------------------------------------

def next_id(prefix: str) -> str:
    """
    open/ と closed/ の両方で同一プレフィックスを持つ既存 md の最大連番 + 1 を採番する。
    例: QA-01.md, QA-02.md が存在すれば QA-03 を返す。
    （closed/ を見ないとクローズ済みタスクと ID が重複するため両方走査する）
    """
    pattern = re.compile(r"^" + re.escape(prefix) + r"-(\d+)(?!\d)", re.IGNORECASE)
    max_num = 0
    for folder in (OPEN_DIR, CLOSED_DIR):
        if not folder.is_dir():
            continue
        for md in folder.glob("*.md"):
            m = pattern.match(md.stem)
            if m:
                max_num = max(max_num, int(m.group(1)))
    return f"{prefix}-{max_num + 1:02d}"


def slugify(title: str, id_: str) -> str:
    """タイトルから安全なスラッグを生成する（最大40文字）。スペース・記号はアンダースコアに置換。"""
    slug = re.sub(r'[\s/\\:*?"<>|]+', "_", title)
    slug = slug[:40].strip("_")
    return slug if slug else id_


def one_line(s: str) -> str:
    """frontmatter に入れる値を 1 行にする。"""
    return re.sub(r"\s+", " ", s or "").strip()


# 本文テンプレート（9 セクション）。用件を上に、背景を下に並べる。
# 「完了条件」の 3 条件はプロジェクトごとに README のクローズ基準で定義し直す。
TASK_BODY = """## 概要
（このタスクで何をするか。1〜3行で用件だけ）

## 対応の意義（なぜやるか）
- 対応しないデメリット: …
- 対応するメリット: …

## 対応後の変更点（利用者視点）
（利用者から見た UI/UX の変化。純粋なバックグラウンド処理のみなら「なし」）

## 対応計画の概要
- 作業項目を箇条書き

## 対応計画の詳細
（各作業項目の具体。対象ファイル・データモデル・移行方針・技術判断）

## 影響・依存
（他タスク・画面・設計書・レビュー観点との関係）

## 完了条件（クローズ3条件）
- [ ] 対象環境へ適用済み
- [ ] 確認者（プロジェクトで定める）の確認
- [ ] 正本（環境情報・設計書・台帳等）への反映
（揃ったら [x]。該当しない条件は `- [x] 該当なし: 理由`。コード変更を伴わないタスクは 2 つ目だけでよい。
残ったまま close.py を実行すると警告が出る）

## 過去の経緯
（これまでの打合せ・決定の変遷。「なぜ今この結論か」）

## 参照情報
（打合せ出典・設計書・関連コミット・関連タスク ID・関連画面 ID）
"""

# 課題の本文（7 セクション）。`## 決定` の 1 行目と落ち先が無いと close.py は閉じない。
# 決定欄の案内は HTML コメントにする（close.py・drops.py はコメントを読まない）。
ISSUE_DECISION_PLACEHOLDER = """<!-- 未決の間は空欄のまま。決着したら 1 行目に決定内容、2 行目以降に落ち先を 1 行ずつ。例:
対象は本社の正社員のみ（2026-09-30 打合せ / SH-02）
→ 反映済: 01 §3
→ APP-03
-->"""

ISSUE_BODY = """## 概要
（何を決める必要があるか。1〜3 行。決まらないと何が止まるか）

## 論点
- …

## 選択肢
- 案A: …
- 案B: …
- 推奨: （あれば。理由 1 行）

## 決着条件
（誰が・何をもって決着とするか。frontmatter の decider / due と食い違わせない）

## 決定
{decision}

## 過去の経緯
（これまでの打合せ・決定の変遷）

## 参照情報
（打合せ出典・設計書・関連タスク ID・関連画面 ID）
"""


def make_template(id_: str, title: str, area: str, today: str, kind: str = "タスク",
                  priority: str = "中", owner: str = "", due: str = "", decider: str = "",
                  tags: list[str] | None = None, decision: str | None = None) -> str:
    """タスク／課題 md のフロントマター＋本文雛形を生成する。課題だけ decider 欄を持つ。"""
    fm = [
        "---",
        f"id: {id_}",
        f"title: {one_line(title)}",
        f"area: {area}",
        f"kind: {kind}",
        "status: 未着手",
        f"priority: {priority}",
    ]
    if kind == "課題":
        fm.append(f"decider: {one_line(decider)}")
    fm += [
        "epic: ",
        f"owner: {one_line(owner)}",
        f"due: {due}",
        "tags: [" + ", ".join(tags or []) + "]",
        "screens: []",
        "source: ",
        f"created: {today}",
        f"updated: {today}",
        "closed: ",
        "---",
        "",
    ]
    if kind == "課題":
        body = ISSUE_BODY.format(decision=decision if decision else ISSUE_DECISION_PLACEHOLDER)
    else:
        body = TASK_BODY
    return "\n".join(fm) + "\n" + body


# ---------------------------------------------------------------------------
# 落ち先（--to）の事前確認
# ---------------------------------------------------------------------------

def check_drops(tos: list[str]) -> list[str]:
    """--to の各値を drops.py で確かめる。drops.py を import できなければ空でないことだけを見る。"""
    try:
        if str(HOOKS_DIR) not in sys.path:
            sys.path.insert(0, str(HOOKS_DIR))
        import drops  # type: ignore
    except Exception:
        note("注記: .claude/hooks/drops.py を読めないため、--to の ID の実在は確かめていません")
        return [f"--to が空: {t!r}" for t in tos if not t.strip()]
    root = str(ROOT)
    items = drops.load_items(root)
    ledger = drops.ledger_ids(root)
    out = []
    for t in tos:
        for p in drops.row_problems(t, items, root, ledger):
            out.append(f"--to「{t}」: {p.message}")
    return out


# ---------------------------------------------------------------------------
# メイン
# ---------------------------------------------------------------------------

def build_parser(areas: dict[str, str]) -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="new.py",
        description="タスク／課題の md を open/ に作る。1 行目に確定した ID を出す（-h は何も作らない）。",
        epilog=(
            f"登録済みの領域（名前=プレフィックス）: {area_list_text(areas)}\n"
            "area にはプレフィックス（大文字小文字は問わない）も使える。未登録なら --add-area 名前:PREFIX。\n"
            "起票してすぐ閉じる: --decided \"決定\" --to \"反映済: 01 §3\"（--kind 課題 を暗黙に付ける）。\n"
            "落ち先の書き方: docs/案件/02_打合せ/README.md。引数の誤りは exit 2 で何も作らない。"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("area", help="領域の名前（areas.json）かプレフィックス")
    p.add_argument("title", help="題名（必須。課題は問いの形「〜するか」で書く）")
    p.add_argument("--kind", choices=KINDS, default=None, help="分類（既定: タスク）")
    p.add_argument("--priority", choices=PRIORITIES, default="中", help="優先度（既定: 中）")
    p.add_argument("--owner", default="", metavar="名前", help="担当")
    p.add_argument("--due", default="", metavar="YYYY-MM-DD", help="期限（タスク・課題共通・任意）")
    p.add_argument("--decider", default="", metavar="ロール", help="課題を決めるロール（SH-02 など。実名は書かない）")
    p.add_argument("--decided", default=None, metavar="決定内容", help="課題を起票してすぐ閉じる。--to と一緒に使う")
    p.add_argument("--to", action="append", default=[], metavar="落ち先",
                   help="--decided の落ち先（繰り返し可）。例: \"反映済: 01 §3\" / APP-03 / \"未決 QA-02\"")
    p.add_argument("--tag", action="append", default=[], metavar="タグ", help="タグ（繰り返し可）")
    p.add_argument("--add-area", default=None, metavar="名前:PREFIX", help="areas.json に領域を足してから起票する")
    return p


def valid_due(due: str) -> bool:
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", due):
        return False
    try:
        datetime.date.fromisoformat(due)
    except ValueError:
        return False
    return True


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except Exception:
            pass
    data = load_areas_data()
    areas: dict[str, str] = {str(k): str(v) for k, v in data["areas"].items()}
    args = build_parser(areas).parse_args(argv)

    # --- 検証（ここまでに何も作らない） -----------------------------------
    title = one_line(args.title)
    if not title:
        die("title が空です（空題名のタスクは作らない）")

    new_area = parse_add_area(args.add_area, areas) if args.add_area else None
    areas_after = dict(areas, **{new_area[0]: new_area[1]}) if new_area else areas
    area = resolve_area(args.area, areas_after)

    due = args.due.strip()
    if due and not valid_due(due):
        die(f"--due は YYYY-MM-DD の実在する日付で書く: {due!r}（「来週」などは日付に直す）")

    kind = args.kind
    decided = one_line(args.decided) if args.decided is not None else None
    tos = [one_line(t) for t in args.to]
    tos = [t[1:].strip() if t.startswith("→") else t for t in tos]
    if decided is not None:
        if kind == "タスク":
            die("--decided は課題に使う（--kind タスク と一緒には使えない）")
        if not decided:
            die("--decided の決定内容が空です")
        if not tos:
            die("--decided には落ち先 --to が要ります（例: --to \"反映済: 01 §3\" / --to APP-03 / --to \"取り下げ: 重複\"）")
        kind = "課題"
    elif tos:
        die("--to は --decided と一緒に使う（未決の課題の落ち先は、決着したときに `## 決定` へ書く）")
    if args.decider:
        if kind == "タスク":
            die("--decider は課題に使う（--kind 課題 を付ける）")
        if kind is None:
            note("--decider があるので分類は 課題 として扱います")
            kind = "課題"
    kind = kind or "タスク"

    if decided is not None:
        problems = check_drops(tos)
        if problems:
            die("落ち先に問題があるため起票しません:\n  " + "\n  ".join(problems)
                + "\n  ID は起票してから new.py の出力を写す。書き方は docs/案件/02_打合せ/README.md")

    # --- 作成 ---------------------------------------------------------------
    if new_area:
        data["areas"][new_area[0]] = new_area[1]
        AREAS_JSON.write_bytes((json.dumps(data, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))
        note(f"領域を追加: {new_area[0]} = {new_area[1]}（{AREAS_JSON.name}）")

    id_ = next_id(areas_after[area])
    today = datetime.date.today().isoformat()
    filename = f"{id_}_{slugify(title, id_)}.md"
    filepath = OPEN_DIR / filename
    if filepath.exists():
        die(f"{filepath} はすでに存在します", 1)

    decision_text = None
    if decided is not None:
        decision_text = decided + "\n" + "\n".join(f"→ {t}" for t in tos)

    OPEN_DIR.mkdir(parents=True, exist_ok=True)
    content = make_template(id_, title, area, today, kind, priority=args.priority, owner=args.owner,
                            due=due, decider=args.decider,
                            tags=[one_line(t) for t in args.tag if one_line(t)], decision=decision_text)
    filepath.write_bytes(content.encode("utf-8"))
    print(id_)
    print(f"作成: open/{filename}（分類: {kind}）", flush=True)

    if decided is not None:
        # close.py が決定と落ち先を確かめて closed/ へ移し、build.py も回す
        r = subprocess.run([sys.executable, str(BASE_DIR / "close.py"), id_])
        if r.returncode != 0:
            print(f"警告: close.py {id_} が失敗しました。open/ に残っています（`## 決定` を直して close.py を再実行）",
                  file=sys.stderr)
            return 1
        return 0

    r = subprocess.run([sys.executable, str(BASE_DIR / "build.py")])
    if r.returncode != 0:
        print("警告: build.py の実行に失敗しました", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
