// The native share sheet for an already-authorized private file. The sheet's
// completion does not prove anything was published or received.
import * as Sharing from "expo-sharing";

import type { FileShareClient } from "../contracts.ts";
import { File } from "expo-file-system";

export class ExpoFileShareClient implements FileShareClient {
  async shareAuthorizedFile(uri: string, mediaType: string): Promise<"SHARED" | "CANCELLED" | "UNAVAILABLE"> {
    if (!(await Sharing.isAvailableAsync())) return "UNAVAILABLE";
    try {
      await Sharing.shareAsync(uri, { mimeType: mediaType, UTI: mediaType === "application/pdf" ? "com.adobe.pdf"
                                                                                                : "public.png" });
      return "SHARED";
    } catch {
      return "CANCELLED";
    }
  }

  /** Called after the sheet closed, never while another app may still be reading the file. */
  async cleanup(uri: string): Promise<void> {
    const file = new File(uri);
    if (file.exists) file.delete();
  }
}
