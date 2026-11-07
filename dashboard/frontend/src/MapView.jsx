import { useEffect, useMemo, useRef, useState } from 'react';
import L from 'leaflet';
import { Expand, MapPin, WifiOff } from 'lucide-react';

export default function MapView({ records, onOpen, compact = false, publicMode = false }) {
  const container = useRef(null);
  const map = useRef(null);
  const markers = useRef(null);
  const lastLocations = useRef(null);
  const open = useRef(onOpen);
  const [offline, setOffline] = useState(false);
  const located = useMemo(() => records.filter(x => (publicMode || x.status === 'verified') && Number.isFinite(x.latitude) && Number.isFinite(x.longitude)), [records, publicMode]);
  const missing = records.filter(x => publicMode || x.status === 'verified').length - located.length;
  open.current = onOpen;

  useEffect(() => {
    // Leaflet 1.x zoom transitions can outlive map.remove() during quick page changes.
    // Immediate zooming avoids a late transition callback against a detached map pane.
    const instance = L.map(container.current, { zoomControl: !compact, scrollWheelZoom: !compact, attributionControl: true, zoomAnimation: false }).setView([20, 0], 2);
    map.current = instance;
    const tiles = L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png', {
      attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>', maxZoom: 19,
    }).addTo(instance);
    const failedTiles = new Set();
    let active = true;
    tiles.on('tileerror', event => { failedTiles.add(event.tile); if (active) setOffline(true); });
    const clearTileError = event => { failedTiles.delete(event.tile); if (active) setOffline(failedTiles.size > 0); };
    tiles.on('tileload', clearTileError);
    tiles.on('tileunload', clearTileError);
    markers.current = L.featureGroup().addTo(instance);
    const resize = new ResizeObserver(() => { if (active) instance.invalidateSize({ pan: false, animate: false }); });
    resize.observe(container.current);
    return () => { active = false; resize.disconnect(); instance.stop(); instance.remove(); map.current = null; markers.current = null; lastLocations.current = null; };
  }, [compact]);

  useEffect(() => {
    if (!markers.current) return;
    const signature = JSON.stringify(located.map(item => [item.id, item.latitude, item.longitude, item.confidence, item.captured_at, item.cropped_url, item.is_demo]));
    // Pending queue updates should not reset a user's map zoom or dismiss an open popup.
    if (signature === lastLocations.current) return;
    lastLocations.current = signature;
    markers.current.clearLayers();
    located.forEach(item => {
      const popup = document.createElement('div');
      const button = document.createElement('button');
      button.type = 'button'; button.className = 'map-popup';
      const image = document.createElement('img'); image.src = item.cropped_url; image.alt = 'Open turtle sighting details';
      const label = document.createElement('strong'); label.textContent = `${publicMode ? item.status + " · " : ""}${item.sighting_id} · ${Math.round(item.confidence * 100)}%`;
      const date = document.createElement('span'); date.textContent = item.captured_at?.replace('T', ' ') || 'Capture time missing';
      button.append(image, label, date);
      if (item.is_demo) { const demo = document.createElement('small'); demo.textContent = 'Synthetic demo location'; button.append(demo); }
      button.addEventListener('click', () => open.current(item.id)); popup.append(button);
      const marker = L.marker([item.latitude, item.longitude], { title: `${item.status} detection ${item.sighting_id}`, icon: L.divIcon({ className: 'turtle-marker', html: '<span></span>', iconSize: [24, 24], iconAnchor: [12, 12] }) })
        .bindPopup(popup).addTo(markers.current);
      marker.getElement()?.setAttribute('aria-label', `Open sighting ${item.sighting_id}`);
    });
    if (located.length) map.current.fitBounds(markers.current.getBounds().pad(0.25), { maxZoom: 15, animate: false });
  }, [located]);

  function fit() { if (located.length) map.current.fitBounds(markers.current.getBounds().pad(0.25), { maxZoom: 16 }); }

  return <div className={`map-wrap ${compact ? 'compact' : ''}`}>
    <div ref={container} className="leaflet-map" aria-label="Map of turtle detections with GPS" />
    <button className="map-fit icon-button" onClick={fit} disabled={!located.length} title="Fit map to all sightings" aria-label="Fit map to all sightings"><Expand size={16} /></button>
    <div className="map-legend"><span className="marker-dot" /> {located.length} located sightings {missing > 0 && <span> · {missing} missing GPS</span>}</div>
    {offline && <div className="map-offline"><WifiOff size={14} /> Map tiles unavailable. Saved GPS markers remain accessible.</div>}
    {!located.length && <div className="map-empty"><MapPin size={24} /><span>No detections with GPS in this view. Locations are never estimated.</span></div>}
  </div>;
}
