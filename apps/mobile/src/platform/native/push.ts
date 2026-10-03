// APNs/FCM device tokens through expo-notifications. Permission is requested
// only from an explicit user action. The raw device token is registered with
// our API; no third-party push relay is used. Payloads are expected to carry
// only ``kind`` and ``object_ref`` (see push connector specification).
import * as Notifications from "expo-notifications";
import { Platform } from "react-native";

import type { DevicePushClient, DevicePushToken, NotificationOpen, PermissionState } from "../contracts.ts";

function toToken(token: Notifications.DevicePushToken): DevicePushToken | null {
  if ((token.type === "ios" || token.type === "android") && typeof token.data === "string" && token.data.length >= 8) {
    return { token: token.data, platform: token.type === "ios" ? "apns" : "fcm" };
  }
  return null;
}

function toOpen(response: Notifications.NotificationResponse | null): NotificationOpen | null {
  if (response === null) return null;
  const data = response.notification.request.content.data ?? {};
  const kind = typeof data.kind === "string" ? data.kind : null;
  const ref = typeof data.object_ref === "string" ? data.object_ref : null;
  return kind === null ? null : { type: kind, reference: ref };
}

export class ExpoDevicePushClient implements DevicePushClient {
  async permission(): Promise<PermissionState> {
    if (Platform.OS !== "ios" && Platform.OS !== "android") return "UNAVAILABLE";
    const status = await Notifications.getPermissionsAsync();
    if (status.granted) return "GRANTED";
    return status.canAskAgain ? "DENIED" : "UNAVAILABLE";
  }

  async requestToken(): Promise<DevicePushToken | null> {
    if (Platform.OS !== "ios" && Platform.OS !== "android") return null;
    let status = await Notifications.getPermissionsAsync();
    if (!status.granted && status.canAskAgain) status = await Notifications.requestPermissionsAsync();
    if (!status.granted) return null;
    try {
      return toToken(await Notifications.getDevicePushTokenAsync());
    } catch {
      // No FCM configuration in this build, or the platform service is unavailable.
      return null;
    }
  }

  onTokenChanged(listener: (token: DevicePushToken) => void): () => void {
    const subscription = Notifications.addPushTokenListener((token) => {
      const parsed = toToken(token);
      if (parsed) listener(parsed);
    });
    return () => subscription.remove();
  }

  onOpen(listener: (open: NotificationOpen) => void): () => void {
    const subscription = Notifications.addNotificationResponseReceivedListener((response) => {
      const open = toOpen(response);
      if (open) listener(open);
    });
    return () => subscription.remove();
  }

  async launchOpen(): Promise<NotificationOpen | null> {
    return toOpen(Notifications.getLastNotificationResponse());
  }
}
