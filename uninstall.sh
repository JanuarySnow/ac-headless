if [ -z "$1" ]; then
  echo "usage: uninstall.sh /path/to/assettocorsa"
  exit 2
fi
exec sh "$(cd "$(dirname "$0")" && pwd)/run.sh" uninstall --ac "$1"
