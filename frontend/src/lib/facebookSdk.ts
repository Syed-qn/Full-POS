/**
 * Loads the Facebook JS SDK once and initialises it for WhatsApp Embedded Signup.
 * Returns the global `FB` object. Safe to call repeatedly — resolves the same
 * in-flight/loaded instance.
 */

// Minimal shape of the bits of the FB SDK we use.
export interface FBLoginResponse {
  authResponse?: { code?: string; accessToken?: string } | null;
  status?: string;
}
export interface FBSdk {
  init(params: Record<string, unknown>): void;
  login(cb: (r: FBLoginResponse) => void, opts: Record<string, unknown>): void;
}

declare global {
  interface Window {
    FB?: FBSdk;
    fbAsyncInit?: () => void;
  }
}

let loader: Promise<FBSdk> | null = null;

export function loadFacebookSdk(appId: string, graphVersion: string): Promise<FBSdk> {
  if (typeof window === "undefined") return Promise.reject(new Error("no window"));
  if (window.FB) return Promise.resolve(window.FB);
  if (loader) return loader;

  loader = new Promise<FBSdk>((resolve, reject) => {
    window.fbAsyncInit = () => {
      window.FB!.init({
        appId,
        autoLogAppEvents: true,
        xfbml: false,
        version: graphVersion, // e.g. "v21.0"
      });
      resolve(window.FB!);
    };

    const id = "facebook-jssdk";
    if (document.getElementById(id)) return; // fbAsyncInit will still fire
    const js = document.createElement("script");
    js.id = id;
    js.src = "https://connect.facebook.net/en_US/sdk.js";
    js.async = true;
    js.defer = true;
    js.crossOrigin = "anonymous";
    js.onerror = () => {
      loader = null;
      reject(new Error("Failed to load the Facebook SDK"));
    };
    document.body.appendChild(js);
  });
  return loader;
}
