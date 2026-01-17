#!/usr/bin/env bash
set -euo pipefail

if [[ $# -lt 2 || $# -gt 3 ]]; then
  echo "Usage: $0 <path.dsn> <out.ses> [freerouting_executable_jar]" >&2
  echo "Defaults jar: freerouting/build/libs/freerouting-executable.jar" >&2
  exit 2
fi

DSN="$1"
OUT_SES="$2"
JAR="${3:-freerouting/build/libs/freerouting-executable.jar}"

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
JDK25="/tmp/temurin25"

if [[ ! -x "$JDK25/bin/java" ]]; then
  rm -rf "$JDK25"
  mkdir -p "$JDK25"
  echo "Downloading Temurin JDK 25 to $JDK25..." >&2
  curl -L --fail -o /tmp/temurin25.tar.gz "https://api.adoptium.net/v3/binary/latest/25/ga/linux/x64/jdk/hotspot/normal/eclipse" >&2
  tar -xzf /tmp/temurin25.tar.gz -C "$JDK25" --strip-components=1
fi

if [[ ! -f "$ROOT/$JAR" ]]; then
  echo "Building Freerouting executable jar..." >&2
  (cd "$ROOT/freerouting" && JAVA_HOME="$JDK25" PATH="$JDK25/bin:$PATH" ./gradlew --no-daemon -q executableJar)
fi

echo "Generating SES from DSN wiring..." >&2
(mkdir -p "$(dirname "$ROOT/$OUT_SES")")
(cd "$ROOT/pardal-pcb/pardal_router_core" && cargo run -q --bin pardal_dsn_to_ses -- "$ROOT/$DSN" "$ROOT/$OUT_SES")

echo "Parsing SES with Freerouting (SessionToEagle)..." >&2
JAVA_HOME="$JDK25" PATH="$JDK25/bin:$PATH" java --class-path "$ROOT/$JAR" "$ROOT/pardal-pcb/pardal_router_core/tools/FreeroutingSesSmoke.java" "$ROOT/$DSN" "$ROOT/$OUT_SES"

echo "OK: Freerouting parsed $OUT_SES" >&2
