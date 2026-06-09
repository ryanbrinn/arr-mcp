#!/usr/bin/env bash
# Seed Sonarr and Radarr with representative test data for media library testing.
# Called by scripts/test-deploy.sh after containers start.
# Idempotent: skips seeding if data is already present.
set -euo pipefail

SONARR_URL="http://localhost:18989"
SONARR_KEY="testsonarrapikey1234567890abcdef"
RADARR_URL="http://localhost:17878"
RADARR_KEY="testradarrapikey1234567890abcdef"

# Wait for a service's API to become ready, up to 60 seconds.
wait_for_service() {
  local name="$1" url="$2" key="$3"
  local tries=0
  echo "  Waiting for $name to be ready..."
  until curl -sf -H "X-Api-Key: $key" "$url/api/v3/system/status" >/dev/null 2>&1; do
    tries=$((tries + 1))
    if [ "$tries" -ge 30 ]; then
      echo "  WARNING: $name not ready after 60s — skipping seed."
      return 1
    fi
    sleep 2
  done
  echo "  $name is ready."
}

seed_sonarr() {
  local count
  count=$(
    curl -sf -H "X-Api-Key: $SONARR_KEY" "$SONARR_URL/api/v3/series" \
      | python3 -c "import sys,json; print(len(json.load(sys.stdin)))"
  )
  if [ "$count" -gt 0 ]; then
    echo "  Sonarr already has $count series — skipping seed."
    return 0
  fi

  # Create root folder so series can be added
  curl -sf -X POST \
    -H "X-Api-Key: $SONARR_KEY" -H "Content-Type: application/json" \
    "$SONARR_URL/api/v3/rootfolder" \
    -d '{"path":"/data/tv"}' >/dev/null

  _add_series() {
    curl -sf -X POST \
      -H "X-Api-Key: $SONARR_KEY" -H "Content-Type: application/json" \
      "$SONARR_URL/api/v3/series" -d "$1" >/dev/null || true
  }

  # Breaking Bad — ended, monitored (badge: wanted/partial)
  _add_series '{"tvdbId":81189,"title":"Breaking Bad","qualityProfileId":1,
    "rootFolderPath":"/data/tv","monitored":true,"seasons":[],
    "addOptions":{"searchForMissingEpisodes":false}}'

  # The Office (US) — ended, monitored (badge: wanted/partial)
  _add_series '{"tvdbId":73244,"title":"The Office (US)","qualityProfileId":1,
    "rootFolderPath":"/data/tv","monitored":true,"seasons":[],
    "addOptions":{"searchForMissingEpisodes":false}}'

  # Planet Earth — ended, unmonitored (badge: unmonitored)
  _add_series '{"tvdbId":79590,"title":"Planet Earth","qualityProfileId":1,
    "rootFolderPath":"/data/tv","monitored":false,"seasons":[],
    "addOptions":{"searchForMissingEpisodes":false}}'

  echo "  Sonarr seeded with 3 series."
}

seed_radarr() {
  local count
  count=$(
    curl -sf -H "X-Api-Key: $RADARR_KEY" "$RADARR_URL/api/v3/movie" \
      | python3 -c "import sys,json; print(len(json.load(sys.stdin)))"
  )
  if [ "$count" -gt 0 ]; then
    echo "  Radarr already has $count movies — skipping seed."
    return 0
  fi

  # Create root folder so movies can be added
  curl -sf -X POST \
    -H "X-Api-Key: $RADARR_KEY" -H "Content-Type: application/json" \
    "$RADARR_URL/api/v3/rootfolder" \
    -d '{"path":"/data/movies"}' >/dev/null

  _add_movie() {
    curl -sf -X POST \
      -H "X-Api-Key: $RADARR_KEY" -H "Content-Type: application/json" \
      "$RADARR_URL/api/v3/movie" -d "$1" >/dev/null || true
  }

  # The Shawshank Redemption — monitored, no file (badge: wanted)
  _add_movie '{"tmdbId":278,"title":"The Shawshank Redemption","qualityProfileId":1,
    "rootFolderPath":"/data/movies","monitored":true,
    "addOptions":{"searchForMovie":false}}'

  # Inception — monitored, no file (badge: wanted)
  _add_movie '{"tmdbId":27205,"title":"Inception","qualityProfileId":1,
    "rootFolderPath":"/data/movies","monitored":true,
    "addOptions":{"searchForMovie":false}}'

  # Oppenheimer — unmonitored (badge: unmonitored)
  _add_movie '{"tmdbId":872585,"title":"Oppenheimer","qualityProfileId":1,
    "rootFolderPath":"/data/movies","monitored":false,
    "addOptions":{"searchForMovie":false}}'

  echo "  Radarr seeded with 3 movies."
}

echo "Seeding media library test data..."
wait_for_service "Sonarr" "$SONARR_URL" "$SONARR_KEY" && seed_sonarr || true
wait_for_service "Radarr" "$RADARR_URL" "$RADARR_KEY" && seed_radarr || true
echo "Media seed complete."
