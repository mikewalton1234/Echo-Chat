# Torrent room stats

Echo-Chat room torrent cards are designed to show the familiar BitTorrent-style fields:

- Seeds
- Leechers
- Completed
- Trackers tried
- Web seed count
- Infohash

## How Echo-Chat finds Seeds / Leechers

Echo-Chat uses three bounded lookup paths:

1. **Declared tracker scrape** — if the `.torrent` or magnet includes tracker announce URLs and `torrent_scrape_enabled=true`, Echo-Chat asks those trackers for `complete`, `incomplete`, and `downloaded` counts.
2. **Public fallback trackers** — if a `.torrent` has no declared trackers, Echo-Chat attaches a small built-in public tracker list and tries those. This restores the old room behavior where trackerless torrents still attempted to show Seeds / Leechers instead of switching to a no-trackers warning.
3. **DHT scrape / peer lookup** — if tracker scrape returns nothing, Echo-Chat performs a short BEP 5 / BEP 33 DHT lookup. BEP 33 can estimate seed and peer counts with Bloom filters. Legacy DHT `get_peers` responses may only return peers, so Echo-Chat may show `Seeds 0` and `Leechers N` from the peer count when no seed split is available.

## Safety controls

User-supplied tracker scraping is still controlled by:

```json
"torrent_scrape_enabled": false
```

The trackerless fallback path uses only Echo-Chat's built-in bounded public tracker list unless you override it:

```json
"torrent_public_fallback_scrape_enabled": true,
"torrent_public_fallback_trackers": [
  "udp://tracker.opentrackr.org:1337/announce",
  "udp://open.stealth.si:80/announce",
  "udp://tracker.torrent.eu.org:451/announce",
  "udp://tracker.moeking.me:6969/announce",
  "https://tracker2.ctix.cn:443/announce",
  "https://tracker.tamersunion.org:443/announce"
]
```

DHT fallback is controlled by:

```json
"torrent_dht_scrape_enabled": true,
"torrent_dht_scrape_timeout_sec": 0.9,
"torrent_dht_scrape_max_queries": 24
```

## Status values

- `refreshed` — declared tracker scrape returned stats.
- `fallback_refreshed` — public fallback tracker scrape returned stats.
- `dht_estimate` — BEP 33 DHT Bloom-filter scrape returned estimated seed/peer counts.
- `dht_peers` — DHT returned peers but no seed split; Echo-Chat shows peers as leechers.
- `no_tracker_response` — trackers were contacted but did not return stats.
- `dht_no_response` — DHT did not return usable swarm data within the bounded lookup.
- `disabled` — user-supplied tracker scraping is disabled for a torrent that supplied its own tracker URLs.

## Notes

The room card intentionally keeps the Seeds / Leechers fields visible. If all lookup paths fail, the fields remain `?`, and the status/details line tells you whether trackers, fallback trackers, or DHT were tried.
## v0.11.0-beta.159 loading badge

Torrent cards now render immediately and show a small **Checking swarm…** spinner/badge while Echo-Chat is still fetching tracker/DHT swarm stats.  The badge is visible during pending/deferred posts, manual refreshes, and DHT fallback lookups, then disappears when lookup succeeds, fails, or is disabled.



## v0.11.0-beta.160 auto-refresh retry fix

Room torrent uploads still post immediately with `defer_swarm=1`. The browser card now waits briefly for the card to render, then runs the same lookup code used by the **Refresh swarm** button. If the first tracker/DHT lookup returns empty, the card retries a few times in the background instead of leaving seeds/leechers stuck at `?` until the user clicks Refresh manually.

This keeps the fast-post behavior while handling slow trackers, DHT warm-up, and first-attempt tracker timeouts.


## Browser-vs-server swarm lookup

Echo-Chat keeps normal seed/leecher lookup on the server. A browser page can use WebRTC/WebTorrent-style peers only; it cannot directly open normal BitTorrent TCP/uTP/UDP sockets or perform regular UDP tracker/DHT operations against the public BitTorrent network. The room card therefore posts immediately in the browser, then asks the server for a best-effort tracker/DHT scrape and updates in-place.

Manual **Refresh swarm** sends `force_refresh=true` so it bypasses cached partial results and tries the tracker/DHT lookup again.
