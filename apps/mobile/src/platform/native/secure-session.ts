import * as SecureStore from "expo-secure-store";

import type { SecureSessionStore } from "../contracts.ts";

const KEY = "inktrospect.session.credential.v1";

export class ExpoSecureSessionStore implements SecureSessionStore {
  read() { return SecureStore.getItemAsync(KEY); }

  write(credential: string) {
    return SecureStore.setItemAsync(KEY, credential, {
      keychainAccessible: SecureStore.WHEN_UNLOCKED_THIS_DEVICE_ONLY,
    });
  }

  clear() { return SecureStore.deleteItemAsync(KEY); }
}
