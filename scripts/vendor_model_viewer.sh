#!/bin/sh
# Обновляет static/vendor/model-viewer из npm с проверкой контрольной суммы пакета.
# Запуск: sh scripts/vendor_model_viewer.sh   (нужны curl, tar и python3)
set -eu

VERSION="4.3.1"
INTEGRITY="sha512-GP+inXhAtY31E8rILVmByA6z8CZZjdlNajddppyI1/j1eIaSQiZcMRaUqTFe7+jv4mzRzwKIOiKBud0apiv+WQ=="
DEST="$(cd "$(dirname "$0")/.." && pwd)/static/vendor/model-viewer"

TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT
cd "$TMP"

curl -fsSL "https://registry.npmjs.org/@google/model-viewer/-/model-viewer-$VERSION.tgz" -o mv.tgz
python3 -I - "$INTEGRITY" <<'PY'
import base64, hashlib, sys
algo, expected = sys.argv[1].split("-", 1)
actual = base64.b64encode(hashlib.new(algo, open("mv.tgz", "rb").read()).digest()).decode()
if actual != expected:
    sys.exit("Контрольная сумма пакета не совпала, файл не установлен")
PY

mkdir extracted
tar -xzf mv.tgz -C extracted package/dist/model-viewer.min.js package/LICENSE
mkdir -p "$DEST"
# Убираем ссылку на source map: сам .map мы не храним, а ManifestStaticFilesStorage на неё споткнётся.
sed '/^\/\/# sourceMappingURL=/d; s|//# sourceMappingURL=model-viewer\.min\.js\.map$||' \
    extracted/package/dist/model-viewer.min.js > "$DEST/model-viewer.min.js"
cp extracted/package/LICENSE "$DEST/LICENSE"
echo "@google/model-viewer $VERSION (Apache-2.0), npm: $INTEGRITY" > "$DEST/VERSION"
echo "Установлен @google/model-viewer $VERSION в $DEST"
