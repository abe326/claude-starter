#!/usr/bin/env python3
"""Claude Code の status line（claude-starter）: モデル名 | モデル別の応答割合 | コンテキスト使用率 | 利用枠。

stdin は statusline の JSON。jq などの外部コマンドは使わない（Windows でも動く）。
モデル別の割合はこのセッションの応答回数（メイン＋サブエージェント）。transcript は追記のみなので、
前回の読み位置から先だけ読んで ~/.claude/cache/model-mix/ に積算する。
"""
import json
import os
import re
import sys
import time

MIX_DIR = os.path.join(os.path.expanduser('~'), '.claude', 'cache', 'model-mix')
MIX_VERSION = 1
MIX_COLORS = {'opus': 33, 'fable': 33, 'sonnet': 32, 'haiku': 36}  # 高位モデルは黄、sonnet は緑、haiku は水色
MODEL_RE = re.compile(r'^claude-([a-z]+)-(\d+(?:-\d{1,2})?)(?:-\d{8})?$')  # claude-opus-5 / claude-fable-5-1 / claude-haiku-4-5-2025...


def fresh():
    return {'v': MIX_VERSION, 'files': {}, 'counts': {}}


def read_new(path, st, counts):
    """path の st['off'] 以降を読み、assistant 応答をモデル別に counts へ足す。縮んでいたら False を返す。"""
    size = os.path.getsize(path)
    if size < st['off']:
        return False
    if size == st['off']:
        return True
    with open(path, 'rb') as f:
        f.seek(st['off'])
        buf = f.read(size - st['off'])
    end = buf.rfind(b'\n')  # 書きかけの最終行は次回に回す
    if end < 0:
        return True
    st['off'] += end + 1
    for line in buf[:end + 1].decode('utf-8', 'replace').split('\n'):
        if '"type":"assistant"' not in line:
            continue
        try:
            o = json.loads(line)
        except ValueError:
            continue
        m = o.get('message') if isinstance(o, dict) and o.get('type') == 'assistant' else None
        if not isinstance(m, dict):
            continue
        mid, model = m.get('id'), m.get('model')
        if not mid or not isinstance(model, str) or not model.startswith('claude-'):  # <synthetic> は除く
            continue
        if mid == st['last']:  # 1 応答が content block ごとに複数行で記録されるので、同じ id は 1 回だけ数える
            continue
        st['last'] = mid
        counts[model] = counts.get(model, 0) + 1
    return True


def model_mix(j):
    tp = j.get('transcript_path')
    sid = j.get('session_id')
    if not tp or not sid:
        return ''
    cache_file = os.path.join(MIX_DIR, re.sub(r'[^\w-]', '_', str(sid), flags=re.ASCII) + '.json')
    loaded = None
    try:
        with open(cache_file, encoding='utf-8') as f:
            loaded = json.load(f)
    except (OSError, ValueError):
        pass  # 初回
    if isinstance(loaded, dict) and loaded.get('v') == MIX_VERSION:
        cache, had_cache = loaded, True
    else:
        cache, had_cache = fresh(), False

    files = [tp]
    sub = os.path.join(os.path.dirname(tp), re.sub(r'\.jsonl$', '', os.path.basename(tp)), 'subagents')
    try:
        files += [os.path.join(sub, f) for f in sorted(os.listdir(sub)) if f.endswith('.jsonl')]
    except OSError:
        pass  # サブエージェント未使用

    dirty = not had_cache
    for _ in range(2):
        shrunk = False
        for f in files:
            st = cache['files'].setdefault(f, {'off': 0, 'last': ''})
            off0 = st['off']
            try:
                if not read_new(f, st, cache['counts']):
                    shrunk = True
            except OSError:
                pass  # 読めないファイルは飛ばす
            if st['off'] != off0:
                dirty = True
        if not shrunk:
            break
        cache = fresh()  # 縮んだファイルがあれば最初から数え直す
        dirty = True

    if dirty:
        try:
            os.makedirs(MIX_DIR, exist_ok=True)
            if not had_cache:  # 古いセッションのキャッシュを掃除
                limit = time.time() - 30 * 86400
                for name in os.listdir(MIX_DIR):
                    p = os.path.join(MIX_DIR, name)
                    if os.path.getmtime(p) < limit:
                        os.unlink(p)
            tmp = '%s.%d.tmp' % (cache_file, os.getpid())
            with open(tmp, 'w', encoding='utf-8') as f:
                json.dump(cache, f)
            os.replace(tmp, cache_file)
        except OSError:
            pass  # 保存できなくても表示はする

    counts = cache['counts']
    total = sum(counts.values())
    if not total:
        return ''
    items = []
    for mid, n in sorted(counts.items(), key=lambda kv: -kv[1]):
        m = MODEL_RE.match(mid)
        label = m.group(1).capitalize() + m.group(2).replace('-', '.') if m else re.sub(r'^claude-', '', mid)
        pct = n * 100 / total
        text = '%s %s%%' % (label, '<1' if pct < 1 else int(pct + 0.5))  # JS の Math.round と同じ丸め
        color = MIX_COLORS.get(m.group(1)) if m else None
        items.append('\x1b[%dm%s\x1b[0m' % (color, text) if color else text)
    return 'mix:' + ' '.join(items)


def pct(v):
    try:
        return '%d%%' % int(float(v) + 0.5)
    except (TypeError, ValueError):
        return ''


def main():
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass
    try:
        j = json.load(sys.stdin)
    except Exception:
        j = {}
    parts = []
    name = (j.get('model') or {}).get('display_name')
    if name:
        parts.append('[%s]' % name)
    try:
        mix = model_mix(j)
    except Exception:
        mix = ''  # mix が無くても他の表示は出す
    if mix:
        parts.append(mix)
    used = pct((j.get('context_window') or {}).get('used_percentage'))
    if used:
        parts.append('ctx:' + used)
    rl = j.get('rate_limits') or {}
    limits = []
    for key, label in (('five_hour', '5h'), ('seven_day', '7d')):
        v = pct((rl.get(key) or {}).get('used_percentage'))
        if v:
            limits.append('%s:%s' % (label, v))
    if limits:
        parts.append(' '.join(limits))
    print(' | '.join(parts))


if __name__ == '__main__':
    main()
