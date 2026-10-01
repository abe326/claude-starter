"""pptx を PowerPoint テンプレート (.potx) に変換する。[Content_Types].xml の本体の型だけを差し替える。"""
import sys, zipfile
src, dst = sys.argv[1], sys.argv[2]
PPTX = "application/vnd.openxmlformats-officedocument.presentationml.presentation.main+xml"
POTX = "application/vnd.openxmlformats-officedocument.presentationml.template.main+xml"
with zipfile.ZipFile(src) as zin, zipfile.ZipFile(dst, "w", zipfile.ZIP_DEFLATED) as zout:
    for item in zin.infolist():
        data = zin.read(item.filename)
        if item.filename == "[Content_Types].xml":
            data = data.replace(PPTX.encode(), POTX.encode())
        zout.writestr(item, data)
print("potx written:", dst)
