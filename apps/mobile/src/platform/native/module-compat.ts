import * as FileSystem from "expo-file-system";
import * as ImagePicker from "expo-image-picker";
import { ImageManipulator } from "expo-image-manipulator";
import * as Linking from "expo-linking";
import * as Notifications from "expo-notifications";
import * as SecureStore from "expo-secure-store";
import * as Sharing from "expo-sharing";
import * as WebBrowser from "expo-web-browser";
import {
  endConnection, fetchProducts, finishTransaction, getAvailablePurchases, initConnection, requestPurchase,
} from "expo-iap";

export const nativeModuleCompatibility = {
  secureStore: SecureStore,
  imagePicker: ImagePicker,
  imageManipulator: ImageManipulator,
  fileSystem: FileSystem,
  sharing: Sharing,
  linking: Linking,
  notifications: Notifications,
  webBrowser: WebBrowser,
  iap: { initConnection, endConnection, fetchProducts, requestPurchase, finishTransaction, getAvailablePurchases },
} as const;
