import { useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { Button } from "../components/Button";
import { StatusPill } from "../components/StatusPill";
import { orderStatusLabel } from "../lib/orderDisplay";
import { Spinner } from "../components/Spinner";
import {
  deleteCustomerAddress,
  patchCustomerAddress,
  patchCustomerProfile,
  setCustomerLoyaltyTier,
} from "../lib/customerApi";
import {
  useCustomerCouponsQuery,
  useCustomerProfileQuery,
  useCustomerWalletQuery,
} from "../lib/queries/dashboard";
import { creditWallet, debitWallet } from "../lib/walletApi";
import type {
  AddressDetailOut,
  AddressPatchIn,
  CustomerProfileOut,
} from "../lib/types";
import s from "./CustomerProfileScreen.module.css";

export function CustomerProfileScreen() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const customerId = id ? Number(id) : null;
  const { data: profile, isPending: loading } = useCustomerProfileQuery(customerId);
  const { data: walletData } = useCustomerWalletQuery(customerId);
  const { data: couponRows = [] } = useCustomerCouponsQuery(profile?.phone);
  const [saving, setSaving] = useState(false);

  function patchProfileCache(next: CustomerProfileOut) {
    if (customerId == null) return;
    queryClient.setQueryData(["customers", "profile", customerId], next);
  }

  const [name, setName] = useState("");
  const [phone, setPhone] = useState("");
  const [optIn, setOptIn] = useState(false);

  const wallet = walletData?.balance ?? null;
  const walletEntries = walletData?.entries ?? [];
  const coupons = couponRows;
  const [creditAmt, setCreditAmt] = useState("");
  const [creditReason, setCreditReason] = useState("");
  const [creditBusy, setCreditBusy] = useState(false);
  const [creditMsg, setCreditMsg] = useState<string | null>(null);

  async function reloadWallet() {
    if (customerId == null) return;
    await queryClient.invalidateQueries({ queryKey: ["customers", "wallet", customerId] });
  }

  async function adjustWallet(kind: "credit" | "debit") {
    if (!id) return;
    setCreditBusy(true);
    setCreditMsg(null);
    try {
      const reason = creditReason || "manager adjustment";
      const fn = kind === "credit" ? creditWallet : debitWallet;
      await fn(Number(id), creditAmt, reason);
      setCreditAmt("");
      setCreditReason("");
      setCreditMsg(kind === "credit" ? "Credit added." : "Amount deducted.");
      await reloadWallet();
    } catch (e) {
      setCreditMsg(e instanceof Error ? e.message : "Could not adjust wallet.");
    } finally {
      setCreditBusy(false);
    }
  }

  useEffect(() => {
    if (!profile) return;
    setName(profile.name ?? "");
    setPhone(profile.phone);
    setOptIn(profile.marketing_opted_in);
  }, [profile]);

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
      patchProfileCache({ ...profile, ...updated });
    } finally {
      setSaving(false);
    }
  }

  async function handleDeleteAddress(addr: AddressDetailOut) {
    if (!profile) return;
    if (!window.confirm(`Delete address "${addr.building ?? addr.room_apartment}"?`)) return;
    await deleteCustomerAddress(profile.id, addr.id);
    patchProfileCache({
      ...profile,
      addresses: profile.addresses.filter((a) => a.id !== addr.id),
    });
  }

  async function handleSaveAddress(addr: AddressDetailOut, patch: AddressPatchIn) {
    if (!profile) return;
    const updated = await patchCustomerAddress(profile.id, addr.id, patch);
    patchProfileCache({
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

          {wallet && (
            <section className={s.card}>
              <h3 className={s.cardTitle}>Wallet</h3>
              <div className={s.stats}>
                <Stat label="Balance" value={`AED ${wallet.balance_aed}`} />
                <Stat label="Available" value={`AED ${wallet.available_aed}`} />
                <Stat label="Status" value={wallet.status} />
              </div>
              {walletEntries.length > 0 && (
                <table className={s.table}>
                  <thead>
                    <tr>
                      <th>Type</th>
                      <th>Amount</th>
                      <th>Date</th>
                    </tr>
                  </thead>
                  <tbody>
                    {walletEntries.slice(0, 5).map((e) => (
                      <tr key={e.id}>
                        <td>{e.type}</td>
                        <td className={s.mono}>AED {e.amount_aed}</td>
                        <td>{new Date(e.created_at).toLocaleDateString()}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
              <div className={s.walletForm}>
                <input
                  type="number" min="0" step="0.01" placeholder="Amount (AED)"
                  value={creditAmt} onChange={(e) => setCreditAmt(e.target.value)}
                  aria-label="credit amount"
                />
                <input
                  type="text" placeholder="Reason"
                  value={creditReason} onChange={(e) => setCreditReason(e.target.value)}
                  aria-label="credit reason"
                />
                <Button
                  disabled={creditBusy || !(Number(creditAmt) > 0)}
                  onClick={() => adjustWallet("credit")}
                >
                  Add credit
                </Button>
                <Button
                  variant="ghost"
                  disabled={creditBusy || !(Number(creditAmt) > 0)}
                  onClick={() => adjustWallet("debit")}
                >
                  Deduct
                </Button>
              </div>
              {creditMsg && <p className={s.walletMsg}>{creditMsg}</p>}
            </section>
          )}

          <section className={s.card}>
            <h3 className={s.cardTitle}>Loyalty</h3>
            <div className={s.stats}>
              <Stat
                label="Tier"
                value={
                  profile.loyalty_tier
                    ? `${{ gold: "🥇", silver: "🥈", bronze: "🥉" }[profile.loyalty_tier] ?? ""} ${profile.loyalty_tier}`
                    : "—"
                }
              />
              <Stat label="Set by" value={profile.loyalty_tier_locked ? "Manager (locked)" : "Auto"} />
            </div>
            <div className={s.walletForm}>
              <select
                aria-label="set loyalty tier"
                value={profile.loyalty_tier ?? ""}
                onChange={async (e) => {
                  const v = e.target.value;
                  const tier = (v === "" ? null : v) as "gold" | "silver" | "bronze" | null;
                  const updated = await setCustomerLoyaltyTier(Number(id), { tier });
                  patchProfileCache(updated);
                }}
              >
                <option value="">None</option>
                <option value="bronze">🥉 Bronze</option>
                <option value="silver">🥈 Silver</option>
                <option value="gold">🥇 Gold</option>
              </select>
              {profile.loyalty_tier_locked && (
                <Button
                  variant="ghost"
                  onClick={async () => {
                    const updated = await setCustomerLoyaltyTier(Number(id), { unlock: true });
                    patchProfileCache(updated);
                  }}
                >
                  Unlock (auto)
                </Button>
              )}
            </div>
          </section>

          {coupons.length > 0 && (
            <section className={s.card}>
              <h3 className={s.cardTitle}>Coupons</h3>
              <table className={s.table}>
                <thead>
                  <tr>
                    <th>Code</th>
                    <th>Discount</th>
                    <th>Status</th>
                    <th>Expires</th>
                  </tr>
                </thead>
                <tbody>
                  {coupons.map((c) => (
                    <tr key={c.id}>
                      <td className={s.mono}>{c.code}</td>
                      <td>
                        {c.discount_type === "percent"
                          ? `${c.percent}%`
                          : `AED ${c.discount_aed}`}
                      </td>
                      <td>{c.status}</td>
                      <td>{c.expires_at ? new Date(c.expires_at).toLocaleDateString() : "—"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </section>
          )}
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
                      <td>
                        <StatusPill
                          status={o.status}
                          label={orderStatusLabel(o.status, {
                            resaleOfOrderId: o.resale_of_order_id,
                            orderNumber: o.order_number,
                          })}
                        />
                      </td>
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
