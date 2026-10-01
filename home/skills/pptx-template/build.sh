#!/usr/bin/env bash
# テンプレートを再生成し、検証とプレビュー作成まで行う。lib/template.js を変えたら必ず実行する。
set -e
cd "$(dirname "$0")"
PPTX_SKILL="$HOME/.claude/skills/pptx"
node build.js
python3 make_potx.py _base.pptx template.potx && rm -f _base.pptx
python3 "$PPTX_SKILL/scripts/office/validate.py" template.pptx | tail -1
mkdir -p preview && rm -f preview/*.jpg preview/*.pdf
python3 "$PPTX_SKILL/scripts/office/soffice.py" --headless --convert-to pdf template.pptx >/dev/null 2>&1 && mv template.pdf preview/
pdftoppm -jpeg -r 80 preview/template.pdf preview/slide && rm -f preview/template.pdf
python3 "$PPTX_SKILL/scripts/thumbnail.py" template.pptx preview/all >/dev/null 2>&1 || true
echo "done: template.pptx template.potx preview/"
