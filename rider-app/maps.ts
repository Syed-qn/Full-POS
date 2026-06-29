/** Turn-by-turn navigation URL — optional fallback; primary UX is the in-app MapPanel. */
export function mapsNavigationUrl(lat: number, lng: number): string {
  return `https://www.google.com/maps/dir/?api=1&destination=${lat},${lng}`;
}