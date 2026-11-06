usage() {
  echo "usage: install.sh [--install-ac] [--steam-user NAME] [--prefix DIR] [--no-steam] [--no-login] [--yes] /path/to/assettocorsa"
  exit 2
}
ac=""
prefix=""
nosteam=""
nologin=""
getac=""
user=""
yes=""
while [ $# -gt 0 ]; do
  case "$1" in
    --prefix) [ -n "$2" ] || usage; prefix="$2"; shift 2 ;;
    --steam-user) [ -n "$2" ] || usage; user="$2"; shift 2 ;;
    --install-ac) getac=1; shift ;;
    --no-steam) nosteam=1; shift ;;
    --no-login) nologin=1; shift ;;
    --yes) yes=1; shift ;;
    -h|--help) usage ;;
    -*) usage ;;
    *) [ -z "$ac" ] || usage; ac="$1"; shift ;;
  esac
done
[ -n "$ac" ] || usage
here="$(cd "$(dirname "$0")" && pwd)"

build=""
if [ ! -f "$here/native/build/achl.dll" ] && [ ! -f "$here/bin/achl.dll" ]; then
  build=1
fi

if command -v apt-get >/dev/null; then pm=apt
elif command -v dnf >/dev/null; then pm=dnf
elif command -v pacman >/dev/null; then pm=pacman
else pm=""
fi

pkg() {
  case "$pm:$1" in
    apt:Xvfb) echo xvfb ;;
    apt:mono) echo mono-runtime ;;
    apt:x86_64-w64-mingw32-gcc) echo gcc-mingw-w64-x86-64 ;;
    apt:vulkan|dnf:vulkan) echo mesa-vulkan-drivers ;;
    apt:lib32) echo lib32gcc-s1 ;;
    dnf:lib32) echo glibc.i686 libstdc++.i686 ;;
    pacman:lib32) echo lib32-gcc-libs ;;
    pacman:vulkan) echo vulkan-swrast ;;
    dnf:Xvfb) echo xorg-x11-server-Xvfb ;;
    dnf:mono) echo mono-core ;;
    dnf:x86_64-w64-mingw32-gcc) echo mingw64-gcc ;;
    pacman:Xvfb) echo xorg-server-xvfb ;;
    pacman:x86_64-w64-mingw32-gcc) echo mingw-w64-gcc ;;
    *) echo "$1" ;;
  esac
}

tools="python3 wine winetricks cabextract Xvfb xdotool mono"
[ -n "$build" ] && tools="$tools x86_64-w64-mingw32-gcc"
missing=""
for t in $tools; do
  command -v "$t" >/dev/null || missing="$missing $t"
done
vk=""
for f in /usr/share/vulkan/icd.d/*.json /etc/vulkan/icd.d/*.json; do
  [ -f "$f" ] && vk=1
done
[ -n "$vk" ] || missing="$missing vulkan"
if [ -n "$getac" ]; then
  l32=""
  for f in /lib/ld-linux.so.2 /lib32/ld-linux.so.2 /usr/lib32/ld-linux.so.2 /usr/lib/ld-linux.so.2; do
    [ -e "$f" ] && l32=1
  done
  [ -n "$l32" ] || missing="$missing lib32"
fi
command -v x11vnc >/dev/null || echo "note: x11vnc is not installed. Only 'steam login --vnc' needs it"

if [ -n "$missing" ]; then
  pkgs=""
  for t in $missing; do
    pkgs="$pkgs $(pkg "$t")"
  done
  case "$pm" in
    apt)
      cmd="sudo apt-get install -y$pkgs"
      case " $missing " in
        *" wine "*)
          if ! dpkg --print-foreign-architectures | grep -qx i386; then
            cmd="sudo dpkg --add-architecture i386 && sudo apt-get update && $cmd wine32:i386"
          fi ;;
      esac ;;
    dnf) cmd="sudo dnf install -y$pkgs" ;;
    pacman) cmd="sudo pacman -S --needed$pkgs" ;;
    *) cmd="" ;;
  esac
  echo "missing programs:$missing"
  if [ -z "$cmd" ]; then
    echo "install them with your package manager, then run install.sh again"
    exit 1
  fi
  echo "to install them: $cmd"
  if [ -z "$yes" ]; then
    if [ ! -t 0 ]; then
      echo "run that, then run install.sh again"
      exit 1
    fi
    printf "run it now? [y/N] "
    read answer
    case "$answer" in
      y|Y|yes) ;;
      *) echo "not installing. Run the command yourself, then run install.sh again"; exit 1 ;;
    esac
  fi
  sh -c "$cmd" || exit 1
fi

if [ -n "$build" ]; then
  sh "$here/native/build.sh" || exit 1
fi

if [ -n "$getac" ]; then
  set -- --install-ac "$ac"
else
  set -- --ac "$ac"
fi
[ -n "$user" ] && set -- "$@" --steam-user "$user"
[ -n "$prefix" ] && set -- "$@" --prefix "$prefix"
[ -n "$nosteam" ] && set -- "$@" --no-steam
set -- "$@" --no-login
sh "$here/run.sh" setup "$@" || exit 1
sh "$here/run.sh" install --ac "$ac" || exit 1
[ -n "$nosteam" ] && exit 0
set --
[ -n "$prefix" ] && set -- --prefix "$prefix"
if [ -n "$nologin" ] || [ ! -t 0 ]; then
  echo "next, log in to Steam once: ./run.sh steam login $*"
  exit 0
fi
if sh "$here/run.sh" steam status "$@" >/dev/null 2>&1; then
  echo "Steam is logged in"
  exit 0
fi
echo "now log in to the Steam client once"
sh "$here/run.sh" steam login "$@" || echo "Steam is not logged in yet. Try again with: ./run.sh steam login $*"
exit 0
