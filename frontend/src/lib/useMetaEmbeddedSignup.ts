import { useCallback, useEffect, useRef, useState } from "react";
import { toast } from "../components/Toaster";
import {
  connectMetaEmbedded,
  fetchMetaEmbedConfig,
  type MetaConfig,
  type MetaEmbedConfig,
} from "./onboardingApi";
import { loadFacebookSdk } from "./facebookSdk";
import { getOnboardPartner } from "./partner";

/**
 * Meta Embedded Signup, extracted from MetaConnectPanel so the SAME popup can be
 * launched from anywhere — the onboarding wizard AND the Settings page — instead
 * of Settings bouncing the manager to /onboarding to press a button there.
 *
 * `connect()` opens Meta's popup: the manager logs into their own Facebook
 * Business, picks a WhatsApp number, and the popup returns an OAuth code while
 * postMessage streams the phone_number_id + waba_id. The backend exchanges the
 * code for their token — nothing is copy-pasted by hand.
 */
export interface MetaEmbeddedSignup {
  /** null while the config is still loading. */
  embed: MetaEmbedConfig | null;
  /** True once the tech-provider app id + Embedded Signup config id are set. */
  enabled: boolean;
  busy: boolean;
  connect: () => Promise<void>;
  /** POS API key minted on connect — shown ONCE, then cleared by the caller. */
  apiKey: string | null;
  clearApiKey: () => void;
}

export function useMetaEmbeddedSignup(
  onConnected?: (cfg: MetaConfig) => void,
): MetaEmbeddedSignup {
  const [embed, setEmbed] = useState<MetaEmbedConfig | null>(null);
  const [busy, setBusy] = useState(false);
  const [apiKey, setApiKey] = useState<string | null>(null);
  // Embedded Signup posts the business's phone_number_id + waba_id via window
  // messages during the popup; we stash the latest here to pair with the code.
  const sessionInfo = useRef<{ phone_number_id?: string; waba_id?: string }>({});
  // Keep the latest callback without re-subscribing the message listener.
  const onConnectedRef = useRef(onConnected);
  onConnectedRef.current = onConnected;

  useEffect(() => {
    fetchMetaEmbedConfig()
      .then(setEmbed)
      .catch(() =>
        setEmbed({ enabled: false, app_id: "", config_id: "", graph_version: "v21.0" }),
      );
  }, []);

  useEffect(() => {
    function onMessage(event: MessageEvent) {
      let host = "";
      try {
        host = new URL(event.origin).hostname;
      } catch {
        return; // opaque/empty origin — not from the FB popup
      }
      if (!/(^|\.)facebook\.com$/.test(host)) return;
      try {
        const data = JSON.parse(event.data);
        if (data?.type !== "WA_EMBEDDED_SIGNUP") return;
        if (data.event === "FINISH" && data.data) {
          sessionInfo.current = {
            phone_number_id: data.data.phone_number_id,
            waba_id: data.data.waba_id,
          };
        }
      } catch {
        /* non-JSON postMessage — ignore */
      }
    }
    window.addEventListener("message", onMessage);
    return () => window.removeEventListener("message", onMessage);
  }, []);

  const finishConnect = useCallback(async (code: string) => {
    const info = sessionInfo.current;
    if (!info.phone_number_id || !info.waba_id) {
      toast("Connection incomplete. Please try again.");
      setBusy(false);
      return;
    }
    try {
      // Partner attribution: the POS embeds the onboarding link with ?partner=<slug>,
      // captured at app start so it survives the signup journey. Absent = standalone.
      const partner = getOnboardPartner();
      const cfg = await connectMetaEmbedded({
        code,
        phone_number_id: info.phone_number_id,
        waba_id: info.waba_id,
        partner: partner || undefined,
      });
      toast("WhatsApp connected ✓");
      if (cfg.api_key) setApiKey(cfg.api_key);
      onConnectedRef.current?.(cfg);
    } catch (e) {
      toast(e instanceof Error ? e.message : "Couldn't finish connecting");
    } finally {
      setBusy(false);
    }
  }, []);

  const connect = useCallback(async () => {
    if (!embed?.enabled) return;
    setBusy(true);
    try {
      const FB = await loadFacebookSdk(embed.app_id, embed.graph_version);
      sessionInfo.current = {};
      // FB.login rejects an async callback ("Expression is of type asyncfunction,
      // not function") — keep this a plain function and kick off async work inside.
      FB.login(
        (resp) => {
          const code = resp?.authResponse?.code;
          if (!code) {
            toast("Connection cancelled. Please try again.");
            setBusy(false);
            return;
          }
          void finishConnect(code);
        },
        {
          config_id: embed.config_id,
          response_type: "code",
          override_default_response_type: true,
          extras: { setup: {}, sessionInfoVersion: "3" },
        },
      );
    } catch (e) {
      toast(e instanceof Error ? e.message : "Couldn't open the Facebook popup");
      setBusy(false);
    }
  }, [embed, finishConnect]);

  return {
    embed,
    enabled: Boolean(embed?.enabled),
    busy,
    connect,
    apiKey,
    clearApiKey: () => setApiKey(null),
  };
}
