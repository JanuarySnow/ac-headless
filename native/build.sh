set -e
cd "$(dirname "$0")"
CC=${CC:-x86_64-w64-mingw32-gcc}
mkdir -p build
$CC -O2 -Wall -shared -o build/achl.dll achl.c -ld3d11 -static-libgcc
$CC -O2 -Wall -municode -o build/achl_launch.exe launch.c -static-libgcc
echo "built native/build/achl.dll and native/build/achl_launch.exe"
