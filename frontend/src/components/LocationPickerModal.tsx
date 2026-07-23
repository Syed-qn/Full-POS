import { useState } from "react";
import { createPortal } from "react-dom";
import { Button } from "./Button";
import { LocationPicker } from "./LocationPicker";
import s from "./LocationPickerModal.module.css";

/**
 * "Set on map" dialog. Edits a LOCAL draft of the coordinates so closing without
 * saving leaves the restaurant's stored location untouched; onSave commits the
 * picked point back to the caller (which persists it).
 */
export function LocationPickerModal({
  lat,
  lng,
  saving = false,
  onSave,
  onClose,
}: {
  lat: number;
  lng: number;
  saving?: boolean;
  onSave: (lat: number, lng: number) => void;
  onClose: () => void;
}) {
  const [draftLat, setDraftLat] = useState(lat);
  const [draftLng, setDraftLng] = useState(lng);

  return createPortal(
    <div className={s.overlay} onClick={saving ? undefined : onClose}>
      <div className={s.modal} onClick={(e) => e.stopPropagation()}>
        <div className={s.header}>
          <h2 className={s.title}>Set restaurant location</h2>
          <button
            className={s.close}
            onClick={onClose}
            aria-label="Close"
            disabled={saving}
          >
            ×
          </button>
        </div>

        <div className={s.body}>
          <LocationPicker
            lat={draftLat}
            lng={draftLng}
            onChange={(la, ln) => {
              setDraftLat(la);
              setDraftLng(ln);
            }}
          />
        </div>

        <div className={s.footer}>
          <span className={s.coords}>
            {draftLat.toFixed(5)}, {draftLng.toFixed(5)}
          </span>
          <div className={s.actions}>
            <Button variant="ghost" onClick={onClose} disabled={saving}>
              Cancel
            </Button>
            <Button onClick={() => onSave(draftLat, draftLng)} disabled={saving}>
              {saving ? "Saving…" : "Save location"}
            </Button>
          </div>
        </div>
      </div>
    </div>,
    document.body,
  );
}
