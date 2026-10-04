// System camera/photo picker and non-AI image preparation.
//
// The library picker is the system picker (PHPicker / Android Photo Picker):
// it needs no broad media-library permission, so none is requested. Camera
// permission is requested only when the user chooses to take a photo.
// Preparation decodes, orients upright, optionally crops/rotates, bounds the
// pixels to the server's intake policy and re-encodes into app-private cache
// storage. The re-encode drops EXIF/GPS metadata. Nothing here measures.
import { Directory, File, Paths } from "expo-file-system";
import { ImageManipulator, SaveFormat } from "expo-image-manipulator";
import * as ImagePicker from "expo-image-picker";

import type {
  CaptureClient, CaptureOutcome, CropRect, ImagePreparer, PermissionState, PickedImage, PreparationResult,
  WorkingImage,
} from "../contracts.ts";
import { planDerivative, MIN_DIMENSION } from "../../work/derivative.ts";

const DIRECTORY = "inktrospect-captures";
const MAX_UPLOAD_BYTES = 20 * 1024 * 1024;
const JPEG_QUALITIES = [0.92, 0.85, 0.75, 0.65];

function permission(status: ImagePicker.PermissionStatus, canAskAgain: boolean): PermissionState {
  if (status === ImagePicker.PermissionStatus.GRANTED) return "GRANTED";
  if (status === ImagePicker.PermissionStatus.DENIED) return canAskAgain ? "DENIED" : "UNAVAILABLE";
  return "DENIED";
}

function picked(result: ImagePicker.ImagePickerResult, source: PickedImage["source"]): CaptureOutcome {
  const asset = result.canceled ? undefined : result.assets[0];
  if (!asset) return { status: "CANCELLED" };
  if (asset.type !== undefined && asset.type !== null && asset.type !== "image") {
    return { status: "FAILED", code: "not_an_image" };
  }
  return { status: "SELECTED", image: {
    uri: asset.uri, width: asset.width, height: asset.height, mimeType: asset.mimeType ?? null,
    fileName: asset.fileName ?? null, fileSize: asset.fileSize ?? null, source,
  } };
}

const PICKER: ImagePicker.ImagePickerOptions = {
  mediaTypes: ["images"],
  quality: 1,
  exif: false,
  allowsEditing: false,
  allowsMultipleSelection: false,
  preferredAssetRepresentationMode: ImagePicker.UIImagePickerPreferredAssetRepresentationMode.Compatible,
};

export class ExpoCaptureClient implements CaptureClient {
  async cameraPermission(): Promise<PermissionState> {
    const result = await ImagePicker.getCameraPermissionsAsync();
    return permission(result.status, result.canAskAgain);
  }

  async takePhoto(): Promise<CaptureOutcome> {
    const request = await ImagePicker.requestCameraPermissionsAsync();
    if (request.status !== ImagePicker.PermissionStatus.GRANTED) {
      return { status: "DENIED", canAskAgain: request.canAskAgain };
    }
    try {
      return picked(await ImagePicker.launchCameraAsync(PICKER), "CAMERA");
    } catch {
      // Simulators and devices without a camera reject the launch.
      return { status: "UNAVAILABLE" };
    }
  }

  async pickPhoto(): Promise<CaptureOutcome> {
    try {
      return picked(await ImagePicker.launchImageLibraryAsync(PICKER), "LIBRARY");
    } catch {
      return { status: "FAILED", code: "picker_failed" };
    }
  }
}

function directory(): Directory {
  const dir = new Directory(Paths.cache, DIRECTORY);
  if (!dir.exists) dir.create({ intermediates: true, idempotent: true });
  return dir;
}

function uniqueName(extension: string): string {
  return `work-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 10)}.${extension}`;
}

async function save(context: ReturnType<typeof ImageManipulator.manipulate>, png: boolean,
                    quality: number): Promise<{ uri: string; width: number; height: number; size: number }> {
  const rendered = await context.renderAsync();
  const result = await rendered.saveAsync({ format: png ? SaveFormat.PNG : SaveFormat.JPEG, compress: quality });
  const source = new File(result.uri);
  const target = new File(directory(), uniqueName(png ? "png" : "jpg"));
  // move() is asynchronous (expo-file-system 57): the copy must be in place before its size, digest or upload.
  await source.move(target);
  const info = target.info();
  // Missing is not zero: an unknown size would slip past the upload bound, so the copy counts as unreadable.
  if (!info.exists || typeof info.size !== "number") throw new Error("prepared_copy_missing");
  return { uri: target.uri, width: result.width, height: result.height, size: info.size };
}

export class ExpoImagePreparer implements ImagePreparer {
  async normalize(image: PickedImage): Promise<PreparationResult> {
    try {
      if (image.width < MIN_DIMENSION || image.height < MIN_DIMENSION) return { ok: false, code: "image_too_small" };
      const plan = planDerivative(image.width, image.height, null);
      if (!plan.ok) return { ok: false, code: plan.code };
      const context = ImageManipulator.manipulate(image.uri);
      if (plan.resize) context.resize({ width: plan.resize.width, height: plan.resize.height });
      // A working copy for review: oriented upright and in app-private storage.
      const keepPng = image.mimeType === "image/png";
      const saved = await save(context, keepPng, 0.95);
      return { ok: true, image: { uri: saved.uri, width: saved.width, height: saved.height,
                                  mediaType: keepPng ? "image/png" : "image/jpeg", source: image.source } };
    } catch {
      return { ok: false, code: "image_unreadable" };
    }
  }

  async rotate(image: WorkingImage, quarterTurns: 1 | 2 | 3): Promise<PreparationResult> {
    try {
      const context = ImageManipulator.manipulate(image.uri).rotate(90 * quarterTurns);
      const saved = await save(context, image.mediaType === "image/png", 0.95);
      return { ok: true, image: { ...image, uri: saved.uri, width: saved.width, height: saved.height } };
    } catch {
      return { ok: false, code: "image_unreadable" };
    }
  }

  async finalize(image: WorkingImage, crop: CropRect | null): Promise<PreparationResult> {
    const plan = planDerivative(image.width, image.height, crop);
    if (!plan.ok) return { ok: false, code: plan.code };
    const png = image.mediaType === "image/png";
    try {
      for (const quality of png ? [1] : JPEG_QUALITIES) {
        const context = ImageManipulator.manipulate(image.uri);
        if (plan.crop) context.crop({ originX: plan.crop.x, originY: plan.crop.y, width: plan.crop.width,
                                      height: plan.crop.height });
        if (plan.resize) context.resize({ width: plan.resize.width, height: plan.resize.height });
        const saved = await save(context, png, quality);
        if (saved.size <= MAX_UPLOAD_BYTES) {
          return { ok: true, image: { uri: saved.uri, width: saved.width, height: saved.height,
                                      mediaType: png ? "image/png" : "image/jpeg", source: image.source } };
        }
        await this.discard(saved.uri);
      }
      return { ok: false, code: "image_too_large" };
    } catch {
      return { ok: false, code: "image_unreadable" };
    }
  }

  async discard(uri: string): Promise<void> {
    const file = new File(uri);
    if (file.exists) file.delete();
  }

  async sweep(keep: ReadonlySet<string>, maxAgeMs: number): Promise<number> {
    const now = Date.now();
    let removed = 0;
    for (const entry of directory().list()) {
      if (!(entry instanceof File) || keep.has(entry.uri)) continue;
      const info = entry.info();
      const age = now - (info.modificationTime ?? info.creationTime ?? 0);
      if (age >= maxAgeMs) {
        entry.delete();
        removed += 1;
      }
    }
    return removed;
  }
}
