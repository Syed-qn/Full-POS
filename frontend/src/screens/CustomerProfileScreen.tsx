import { useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { Button } from "../components/Button";
import { StatusPill } from "../components/StatusPill";
import { Spinner } from "../components/Spinner";
import {
  deleteCustomerAddress,
  getCustomerProfile,
  patchCustomerAddress,
  patchCustomerProfile,
} from "../lib/customerApi";
import type { AddressDetailOut, AddressPatchIn, CustomerProfileOut } from "../lib/types";
import s from "./CustomerProfileScreen.module.css";

export function CustomerProfileScreen() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const [profile, setProfile] = useState<CustomerProfileOut | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);

  const [name, setName] = useState("");
  const [phone, setPhone] = useState("");
  const [optIn, setOptIn] = useState(false);

  useEffect(() => {
    if (!id) return;
    getCustomerProfile(Number(id))
      .then((p) => {
        setProfile(p);
        setName(p.name ?? "");
        setPhone(p.phone);
        setOptIn(p.marketing_opted_in);
      })
      .finally(() => setLoading(false));
  }, [id]);

  if (loading) return <Spinner />;
  if (!profile) return <p className={s.error}>Customer not found</p>;

  const identityDirty =
    name !== (profile.name ?? "") ||
    phone !== profile.phone ||
    optIn !== profile.marketing_opted_in;

  async function saveIdentity() {
    if (!profile) return;
    setSaving(true);
    try {
      const updated = await patchCustomerProfile(profile.id, {
        name: name || null,
        phone: phone || null,
        marketing_opted_in: optIn,
      });
      setProfile({ ...profile, ...updated });
    } finally {
      setSaving(false);
    }
  }

  async function handleDeleteAddress(addr: AddressDetailOut) {
    if (!profile) return;
    if (!window.confirm(`Delete address "${addr.building ?? addr.room_apartment}"?`)) return;
    await deleteCustomerAddress(profile.id, addr.id);
    setProfile({
      ...profile,
      addresses: profile.addresses.filter((a) => a.id !== addr.id),
    });
  }

  async function handleSaveAddress(addr: AddressDetailOut, patch: AddressPatchIn) {
    if (!profile) return;
    const updated = await patchCustomerAddress(profile.id, addr.id, patch);
    setProfile({
      ...profile,
      addresses: profile.addresses.map((a) => (a.id === updated.id ? updated : a)),
    });
  }

  return (
    <div className={s.screen}>
      <div className={s.header}>
        <button className={s.back} onClick={() => navigate(-1)}>← Back</button>
        <h2 className={s.title}>{profile.name ?? profile.phone}</h2>
      </div>

      <div className={s.grid}>
        <div className={s.left}>
          <section className={s.card}>
            <h3 className={s.cardTitle}>Identity</h3>
            <label className={s.label}>Name</label>
            <input className={s.input} value={name} onChange={(e) => setName(e.target.value)} />
            <label className={s.label}>Phone</label>
            <input className={s.input} value={phone} onChange={(e) => setPhone(e.target.value)} />
            <div className={s.toggleRow}>
              <label className={s.label}>WhatsApp Marketing</label>
              <button
                className={`${s.toggle} ${optIn ? s.toggleOn : s.toggleOff}`}
                onClick={() => setOptIn(!optIn)}
              >
                {optIn ? "OPT-IN" : "OPT-OUT"}
              </button>
            </div>
            <div className={s.saveRow}>
              <Button onClick={saveIdentity} disabled={!identityDirty || saving}>
                {saving ? "Saving…" : "Save"}
              </Button>
            </div>
          </section>

          <section className={s.card}>
            <h3 className={s.cardTitle}>Stats</h3>
            <div className={s.stats}>
              <Stat label="Total Orders" value={String(profile.total_orders)} />
              <Stat label="Total Spend" value={`AED ${profile.total_spend}`} />
              <Stat
                label="First Order"
                value={profile.first_order_at
                  ? new Date(profile.first_order_at).toLocaleDateString()
                  : "—"}
              />
              <Stat
                label="Last Order"
                value={profile.last_order_at
                  ? new Date(profile.last_order_at).toLocaleDateString()
                  : "—"}
              />
              <Stat label="Usually Orders" value={profile.usual_order_time ?? "—"} />
            </div>
          </section>
        </div>

        <div className={s.right}>
          <section className={s.card}>
            <h3 className={s.cardTitle}>Addresses ({profile.addresses.length})</h3>
            {profile.addresses.length === 0 ? (
              <p className={s.empty}>No saved addresses</p>
            ) : (
              profile.addresses.map((addr) => (
                <AddressCard
                  key={addr.id}
                  addr={addr}
                  onDelete={() => handleDeleteAddress(addr)}
                  onSave={(patch) => handleSaveAddress(addr, patch)}
                />
              ))
            )}
          </section>

          <section className={s.card}>
            <h3 className={s.cardTitle}>Recent Orders</h3>
            {profile.recent_orders.length === 0 ? (
              <p className={s.empty}>No orders yet</p>
            ) : (
              <table className={s.table}>
                <thead>
                  <tr>
                    <th>Order</th>
                    <th>Status</th>
                    <th>Total</th>
                    <th>Date</th>
                  </tr>
                </thead>
                <tbody>
                  {profile.recent_orders.map((o) => (
                    <tr key={o.id} className={s.orderRow} onClick={() => navigate(`/orders?open=${o.id}`)}>
                      <td className={s.mono}>{o.order_number}</td>
                      <td><StatusPill status={o.status} /></td>
                      <td className={s.mono}>AED {o.total}</td>
                      <td>{new Date(o.created_at).toLocaleDateString()}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </section>
        </div>
      </div>
    </div>
  );
}

function AddressCard({
  addr,
  onDelete,
  onSave,
}: {
  addr: AddressDetailOut;
  onDelete: () => void;
  onSave: (patch: AddressPatchIn) => Promise<void>;
}) {
  const [editing, setEditing] = useState(false);
  const [aptRoom, setAptRoom] = useState(addr.room_apartment ?? "");
  const [building, setBuilding] = useState(addr.building ?? "");
  const [receiverName, setReceiverName] = useState(addr.receiver_name ?? "");
  const [notes, setNotes] = useState(addr.additional_details ?? "");
  const [saving, setSaving] = useState(false);

  async function save() {
    setSaving(true);
    try {
      await onSave({
        room_apartment: aptRoom || null,
        building: building || null,
        receiver_name: receiverName || null,
        additional_details: notes || null,
      });
      setEditing(false);
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className={s.addressCard}>
      {editing ? (
        <>
          <input className={s.input} value={aptRoom} onChange={(e) => setAptRoom(e.target.value)} placeholder="Apt / Room" />
          <input className={s.input} value={building} onChange={(e) => setBuilding(e.target.value)} placeholder="Building" />
          <input className={s.input} value={receiverName} onChange={(e) => setReceiverName(e.target.value)} placeholder="Receiver name" />
          <input className={s.input} value={notes} onChange={(e) => setNotes(e.target.value)} placeholder="Notes" />
          <div className={s.addrActions}>
            <Button onClick={save} disabled={saving}>{saving ? "Saving…" : "Save"}</Button>
            <button className={s.cancel} onClick={() => setEditing(false)}>Cancel</button>
          </div>
        </>
      ) : (
        <>
          <p className={s.addrLine}>{[addr.room_apartment, addr.building].filter(Boolean).join(", ") || "—"}</p>
          {addr.receiver_name && <p className={s.addrMeta}>Receiver: {addr.receiver_name}</p>}
          {addr.additional_details && <p className={s.addrMeta}>{addr.additional_details}</p>}
          <div className={s.addrActions}>
            <button className={s.editBtn} onClick={() => setEditing(true)}>Edit</button>
            <button className={s.deleteBtn} onClick={onDelete}>Delete</button>
          </div>
        </>
      )}
    </div>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className={s.stat}>
      <span className={s.statValue}>{value}</span>
      <span className={s.statLabel}>{label}</span>
    </div>
  );
}
