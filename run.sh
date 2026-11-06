here="$(cd "$(dirname "$0")" && pwd)"
PYTHONPATH="$here${PYTHONPATH:+:$PYTHONPATH}" exec python3 -u -m achl "$@"
