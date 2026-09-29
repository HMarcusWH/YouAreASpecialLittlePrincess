import * as ImagePicker from "expo-image-picker";
import { ImageManipulator, SaveFormat } from "expo-image-manipulator";

import type { CaptureClient, LocalCapture, PermissionState } from "../contracts.ts";

function permission(status: ImagePicker.PermissionStatus, canAskAgain: boolean): PermissionState {
  if (status === ImagePicker.PermissionStatus.GRANTED) return "GRANTED";
  if (status === ImagePicker.PermissionStatus.DENIED) return canAskAgain ? "DENIED" : "UNAVAILABLE";
  return "LIMITED";
}

async function normalize(asset: ImagePicker.ImagePickerAsset, source: LocalCapture["source"]): Promise<LocalCapture> {
  const context = ImageManipulator.manipulate(asset.uri);
  const rendered = await context.renderAsync();
  const jpeg = await rendered.saveAsync({ format: SaveFormat.JPEG, compress: 0.95 });
  return {
    localUri: jpeg.uri,
    width: jpeg.width,
    height: jpeg.height,
    mimeType: "image/jpeg",
    source,
    originalMimeType: asset.mimeType ?? null,
    fileName: asset.fileName ?? null,
    orientationMetadata: asset.exif ? "PRESENT" : "UNKNOWN",
  };
}

export class ExpoCaptureClient implements CaptureClient {
  async cameraPermission() {
    const result = await ImagePicker.getCameraPermissionsAsync();
    return permission(result.status, result.canAskAgain);
  }

  async libraryPermission() {
    const result = await ImagePicker.getMediaLibraryPermissionsAsync();
    if (result.accessPrivileges === "limited") return "LIMITED";
    return permission(result.status, result.canAskAgain);
  }

  async takePhoto() {
    const permissionResult = await ImagePicker.requestCameraPermissionsAsync();
    if (permissionResult.status !== ImagePicker.PermissionStatus.GRANTED) return null;
    const result = await ImagePicker.launchCameraAsync({ mediaTypes: ["images"], quality: 1, exif: true });
    return result.canceled || !result.assets[0] ? null : normalize(result.assets[0], "CAMERA");
  }

  async pickPhoto() {
    const permissionResult = await ImagePicker.requestMediaLibraryPermissionsAsync();
    if (permissionResult.status !== ImagePicker.PermissionStatus.GRANTED &&
        permissionResult.accessPrivileges !== "limited") return null;
    const result = await ImagePicker.launchImageLibraryAsync({ mediaTypes: ["images"], quality: 1, exif: true });
    return result.canceled || !result.assets[0] ? null : normalize(result.assets[0], "LIBRARY");
  }
}
