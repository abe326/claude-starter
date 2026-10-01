#!/usr/bin/env python3
"""PostToolUse hook (Write|Edit|MultiEdit): 触ったファイルを記録し、設計書・落ち先を思い出させる。

stdin の JSON から tool_input.file_path を読み、次の順に処理する。ブロックはしない（常に exit 0）。

  1. ルート内なら、触ったパスを pickup_state に記録する（Stop hook pickup_check.py の材料。.work/ も記録）
  1b. .claude/project.json の save_cues の glob に当たれば、ファイルと cue ごとにセッション 1 回「[保存の促し] <cue>」
     （置き場に関係なく見る。下の 2・3 の出力と一緒に返す）
  2. 打合せ記録（docs/案件/02_打合せ/*.md）: フェーズに関係なく、ファイルごとにセッション 1 回
     「[落ち先] … 各行に落ち先 …」を返す（影響マップは引かない）
  3. それ以外は docs/設計書/README.md の影響マップ（解釈は impact_map.py。差し込み口
     .claude/hooks/impact_map_local.py があればその targets() の結果も足す）に当たれば、
     phase.level("design_docs_reminder", <フェーズ>) で出し分ける
       none → 何も出さない
       info（Sketch）→ セッションで 1 回だけ「[設計書候補] … Sketch の間は直さなくてよい …」
       warn（Build）→ 候補の組み合わせごとに 1 回「[設計書追随] … 区切りで、決まったことを 1 行拾う」
     既出のキーにフェーズを含めるので、フェーズを切り替えた直後にはもう一度出る

  - .work/・.claude/・docs/案件/01_タスク管理/ 配下は 2・3 の対象外
  - フェーズは phase.read_phase(root)。import できない・読めないときは「Sketch」扱い（静かな側に倒す）
  - 既出の記録は pickup_state.already_seen（state は tempfile.gettempdir()/claude_docs_reminder_<session_id>.json。
    環境変数 CLAUDE_DOCS_REMINDER_STATE_DIR で置き場を変えられる）。session_id が無ければ毎回出す
  - 例外はすべて握りつぶして exit 0（編集を妨げない）
パスの正規化は work_area_guard.py と同じ（Windows / Git Bash / WSL 表記を吸収）。
"""
import json
import os
import re
import sys

sys.dont_write_bytecode = True
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from impact_map import addable_docs, load_impact_map, local_targets, match_rows, resolve_targets  # noqa: E402
from work_area_guard import relative_to_root  # noqa: E402

SKIP_PREFIXES = (".work/", ".claude/", "docs/案件/01_タスク管理/")
README = "docs/設計書/README.md"
MEETING_DIR = "docs/案件/02_打合せ/"


def _pickup_state():
    try:
        import pickup_state  # noqa: WPS433
        return pickup_state
    except Exception:
        return None


def already_seen(session_id, key: str) -> bool:
    """既出なら True。session_id が無い・状態を扱えないときは False（毎回出す）。"""
    if not isinstance(session_id, str) or not session_id:
        return False
    ps = _pickup_state()
    if ps is None:
        return False
    try:
        return ps.already_seen(session_id, key)
    except Exception:
        return False


def record_touch(session_id, rel: str) -> None:
    ps = _pickup_state()
    if ps is None:
        return
    try:
        ps.append(session_id, "touch", rel)
    except Exception:
        pass


def save_cues(rel: str, root: str) -> list[str]:
    """project.json の save_cues のうち rel に当たるものの cue。読めなければ空。"""
    try:
        import project_config  # noqa: WPS433
        from impact_map import glob_matches  # noqa: WPS433
        return [c["cue"] for c in project_config.load(root)["save_cues"]
                if any(glob_matches(rel, g) for g in c["globs"])]
    except Exception:
        return []


def current_level(root: str) -> tuple[str, str]:
    """(フェーズ, design_docs_reminder のレベル)。分からなければ (Sketch, info)。"""
    try:
        import phase as phase_mod  # noqa: WPS433
        ph = phase_mod.read_phase(root)
        return ph, phase_mod.level("design_docs_reminder", ph)
    except Exception:
        return "Sketch", "info"


def is_meeting(rel: str) -> bool:
    if not rel.startswith(MEETING_DIR) or not rel.endswith(".md"):
        return False
    name = rel[len(MEETING_DIR):]
    return "/" not in name and name != "README.md"


NON_SOURCE_PREFIXES = ("docs/", "scripts/", ".work/", ".claude/")
NON_SOURCE_FILES = {"CLAUDE.md", "README.md", "CHANGELOG.md", ".gitignore", ".gitattributes", ".editorconfig",
                    ".env.example", "環境情報.md", "案件情報.md"}


def is_source(rel: str) -> bool:
    """実装・設定の変更か（文書・スケルトンの仕組み・作業領域・ルート直下の定型ファイル以外）。"""
    return not rel.startswith(NON_SOURCE_PREFIXES) and rel not in NON_SOURCE_FILES


def suggest_level(phase: str) -> str:
    """phase_suggest のレベル（Build では none）。分からなければ none（静かな側に倒す）。"""
    try:
        import phase as phase_mod  # noqa: WPS433
        return phase_mod.level("phase_suggest", phase)
    except Exception:
        return "none"


def candidate_example(candidates: list[str]) -> str:
    """落ち先の書き方の例（候補: 05 §n）。設計書の番号が取れなければ NN。"""
    for c in candidates:
        m = re.match(r"^docs/設計書/(\d{2})-", c)
        if m:
            return f"候補: {m.group(1)} §n"
    return "候補: NN §n"


def emit(msg: str) -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    print(json.dumps({"hookSpecificOutput": {"hookEventName": "PostToolUse", "additionalContext": msg}},
                     ensure_ascii=False))


def main() -> int:
    try:
        raw = sys.stdin.buffer.read().decode("utf-8", errors="replace")
        data = json.loads(raw) if raw.strip() else {}
        if data.get("tool_name") not in ("Edit", "Write", "MultiEdit"):
            return 0
        tool_input = data.get("tool_input") or {}
        file_path = tool_input.get("file_path") or tool_input.get("path")
        if not file_path or not isinstance(file_path, str):
            return 0
        root = os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd()
        rel = relative_to_root(file_path, root)
        if rel is None:
            return 0
        session_id = data.get("session_id")
        record_touch(session_id, rel)

        # 保存を起点にした促し（project.json の save_cues）: 置き場に関係なく、ファイルごとにセッション 1 回
        cue_notes = [f"[保存の促し] {c}" for c in save_cues(rel, root)
                     if not already_seen(session_id, f"cue:{rel}:{c}")]

        # 打合せ記録: フェーズより先に分岐。影響マップは引かない
        if is_meeting(rel):
            if not already_seen(session_id, f"meeting:{rel}"):
                cue_notes.append(f"[落ち先] {rel}: 決定・未決・宿題の各行に落ち先（→ 反映済: 01 §3 / → APP-03 / → 未決 QA-01）。"
                                 "ID は起票してから書く。区切りで pickup スキル")
            if cue_notes:
                emit("\n".join(cue_notes))
            return 0

        if rel.startswith(SKIP_PREFIXES):
            if cue_notes:
                emit("\n".join(cue_notes))
            return 0
        rows = match_rows(rel, load_impact_map(os.path.join(root, README)))
        targets: list[str] = []
        for r in rows:
            targets += [t for t in r.targets if t not in targets]
        targets += [t for t in local_targets(rel, root) if t not in targets]   # 差し込み口（任意）
        candidates = [t for t in resolve_targets(targets, root) if t != rel]

        phase, lvl = current_level(root)
        notes: list[str] = cue_notes
        # 実装・設定の変更を始めた（Sketch の間だけ、セッション 1 回）: Build の目安。切り替えは AI が判断する
        if is_source(rel) and suggest_level(phase) != "none" and not already_seen(session_id, f"build-nudge:{phase}"):
            notes.append(f"[フェーズ] 実装・設定の変更を始めた（{rel}）。Build の目安に当たる。AI が判断して "
                         "python3 .claude/hooks/phase.py --set Build で切り替え、報告で 1 行伝える")
        # まだ足していない設計書に関わる（文書ごとにセッション 1 回）: 足す候補。足すのは承認後
        for doc in addable_docs(rel, root):
            if not already_seen(session_id, f"addable:{doc}"):
                no = doc[:2]
                notes.append(f"[文書の候補] {rel} はまだ無い {doc} に関わる。要るなら足す候補として報告し、承認を得てから "
                             f"python3 scripts/add_doc.py {no}（それまでの決定は課題の --to に「候補: {no} §n」）")

        if candidates and lvl == "info":
            # Sketch の間: 候補の組み合わせに関係なくセッションで 1 回だけ
            if not already_seen(session_id, f"phase:{phase}:info"):
                notes.append(f"[設計書候補] {rel} の変更は {'、'.join(candidates)} に関わる。{phase} の間は直さなくてよい。"
                             f"決まったことなら落ち先に「→ {candidate_example(candidates)}」と書く（pickup スキル）")
        elif candidates and lvl == "warn":
            if not already_seen(session_id, f"phase:{phase}|" + "|".join(sorted(candidates))):
                notes.append(f"[設計書追随] {rel} を変更。更新候補: {'、'.join(candidates)}。"
                             f"区切りで、決まったことを 1 行拾う（sync-design-docs スキル。影響マップ: {README}）")
        if notes:
            emit("\n".join(notes))
    except Exception:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
